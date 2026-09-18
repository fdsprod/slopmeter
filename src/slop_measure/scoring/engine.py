"""Score aggregate measurements against compatible reference populations."""

from bisect import bisect_left
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import assert_never

from slop_measure.domain.metrics import (
    CalibratedScore,
    MeasuredMetric,
    MetricResult,
    MetricScope,
    MetricUnit,
    UnavailableMetric,
    UnavailableReason,
)
from slop_measure.domain.reports import (
    AnalysisReport,
    CohortResult,
    FileResult,
    MeasuredSnapshotScore,
    Provenance,
    ScoreUnavailableReason,
    SnapshotScore,
    UnavailableSnapshotScore,
)
from slop_measure.domain.scoring import (
    CalibrationProfile,
    CalibrationSettings,
    FilePopulation,
    MetricDistribution,
    ReferencePopulation,
    ScoreContribution,
    ScoreInput,
    ScoreModel,
    ScoreTransform,
)


def compatible(profile: CalibrationProfile, language: str, provenance: Provenance) -> bool:
    """Match every metric definition and effective option used by the reference."""
    analyzer = next((item for item in provenance.analyzers if item.language == language), None)
    if (
        profile.language != language
        or analyzer is None
        or analyzer.rule_set_version != profile.rule_set_version
        or analyzer.clone_normalization_version != profile.clone_normalization_version
        or profile.settings != CalibrationSettings.from_config(provenance.config)
    ):
        return False
    versions = {item.metric_id: item.version for item in provenance.metrics}
    return all(versions.get(item.metric_id) == item.version for item in profile.metric_versions)


def percentile(value: float, distribution: MetricDistribution) -> Decimal:
    """Return the percentage of reference observations strictly below the input."""
    if value <= 0:
        return Decimal(0)
    return Decimal(bisect_left(distribution.values, value) * 100) / distribution.sample_count


def _eligible_model(
    profile: CalibrationProfile, metrics: dict[str, MetricResult]
) -> ScoreModel | None:
    erosion = metrics.get("m4.erosion")
    eligibility = (
        "no-functions"
        if isinstance(erosion, UnavailableMetric)
        and erosion.reason is UnavailableReason.NO_FUNCTIONS
        else "all-metrics"
    )
    model = next((item for item in profile.score_models if item.eligibility == eligibility), None)
    if model is None or any(
        not isinstance(metrics.get(item.metric_id), MeasuredMetric) for item in model.inputs
    ):
        return None
    return model


def select_population(
    profile: CalibrationProfile, model_id: str, scope: MetricScope, sloc: int
) -> ReferencePopulation | None:
    """Select a cohort and scope reference without averaging file observations."""
    for population in profile.populations:
        if (population.kind, population.cohort, population.model_id) != (
            scope.kind,
            scope.cohort,
            model_id,
        ):
            continue
        if isinstance(population, FilePopulation) and not (
            population.min_sloc <= sloc
            and (population.max_sloc is None or sloc < population.max_sloc)
        ):
            continue
        return population
    return None


def _transformed(rank: Decimal, raw: float, transform: ScoreTransform) -> Decimal:
    match transform:
        case ScoreTransform.PERCENTILE:
            return rank
        case ScoreTransform.SEVERITY_WEIGHTED:
            return rank * Decimal(str(raw))
        case _:
            assert_never(transform)


def _contributions(
    model: ScoreModel, population: ReferencePopulation, metrics: dict[str, MetricResult]
) -> tuple[ScoreContribution, ...]:
    distributions = {item.metric_id: item for item in population.distributions}
    observations: list[tuple[ScoreInput, float, Decimal, float, ScoreTransform]] = []
    for item in sorted(model.inputs, key=lambda item: item.metric_id):
        metric = metrics[item.metric_id]
        assert isinstance(metric, MeasuredMetric)  # noqa: S101 - checked by model selection
        if metric.raw.unit is not MetricUnit.RATIO:
            raise ValueError("snapshot calibration requires ratio inputs")
        observations.append(
            (
                item.metric_id,
                metric.raw.value,
                percentile(metric.raw.value, distributions[item.metric_id]),
                item.weight,
                item.transform,
            )
        )
    tenths = [
        _transformed(rank, raw, transform) * Decimal(str(weight)) * 10
        for _, raw, rank, weight, transform in observations
    ]
    allocated = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in tenths]
    target = int(sum(tenths, Decimal(0)).to_integral_value(rounding=ROUND_HALF_UP))
    order = sorted(
        range(len(tenths)),
        key=lambda index: (-(tenths[index] - allocated[index]), observations[index][0]),
    )
    for index in order[: target - sum(allocated)]:
        allocated[index] += 1
    return tuple(
        ScoreContribution(
            metric_id=metric_id,
            raw_value=raw,
            percentile=float(rank),
            weight=weight,
            transform=transform,
            points=float(Decimal(points) / 10),
        )
        for (metric_id, raw, rank, weight, transform), points in zip(
            observations, allocated, strict=True
        )
    )


def _missing(reason: ScoreUnavailableReason) -> UnavailableSnapshotScore:
    return UnavailableSnapshotScore(reason=reason)


def _context_failure(
    sloc: int, language: str, provenance: Provenance, profile: CalibrationProfile | None
) -> UnavailableSnapshotScore | None:
    if sloc == 0:
        return _missing(ScoreUnavailableReason.NO_SOURCE_LINES)
    if profile is None:
        return _missing(ScoreUnavailableReason.CALIBRATION_MISSING)
    if not compatible(profile, language, provenance):
        return _missing(ScoreUnavailableReason.CALIBRATION_INCOMPATIBLE)
    return None


def score_snapshot(
    metrics: tuple[MetricResult, ...],
    *,
    sloc: int,
    language: str,
    provenance: Provenance,
    profile: CalibrationProfile | None,
) -> SnapshotScore:
    """Produce exact displayed contributions or an explicit unavailable result."""
    failure = _context_failure(sloc, language, provenance, profile)
    if failure is not None:
        return failure
    assert profile is not None  # noqa: S101 - checked by context validation
    if not metrics:
        return _missing(ScoreUnavailableReason.REQUIRED_METRIC_UNAVAILABLE)
    by_id = {item.metric_id: item for item in metrics}
    if len(by_id) != len(metrics) or any(item.scope != metrics[0].scope for item in metrics):
        raise ValueError("scoring requires unique metrics in one scope")
    model = _eligible_model(profile, by_id)
    if model is None:
        return _missing(ScoreUnavailableReason.REQUIRED_METRIC_UNAVAILABLE)
    population = select_population(profile, model.model_id, metrics[0].scope, sloc)
    if population is None:
        return _missing(
            ScoreUnavailableReason.REQUIRED_METRIC_UNAVAILABLE
            if model.eligibility == "no-functions"
            else ScoreUnavailableReason.CALIBRATION_INCOMPATIBLE
        )
    contributions = _contributions(model, population, by_id)
    total = sum((Decimal(str(item.points)) for item in contributions), Decimal(0))
    band = next(band.label for band in reversed(profile.bands) if total >= Decimal(str(band.lower)))
    return MeasuredSnapshotScore(
        points=float(total),
        profile_id=profile.profile_id,
        model_id=model.model_id,
        band=band,
        contributions=contributions,
    )


def _score_result(
    result: FileResult | CohortResult,
    *,
    language: str,
    provenance: Provenance,
    profile: CalibrationProfile | None,
    failure: ScoreUnavailableReason | None,
) -> FileResult | CohortResult:
    sloc = (
        result.evidence.sloc
        if isinstance(result, FileResult)
        else sum(file.evidence.sloc for file in result.files)
    )
    score = score_snapshot(
        result.metrics, sloc=sloc, language=language, provenance=provenance, profile=profile
    )
    if failure is not None and sloc:
        score = _missing(failure)
    elif isinstance(result.score, UnavailableSnapshotScore) and (
        profile is None
        or (sloc == 0 and result.score.reason is ScoreUnavailableReason.REQUIRED_METRIC_UNAVAILABLE)
    ):
        score = result.score
    population = (
        select_population(profile, score.model_id, result.metrics[0].scope, sloc)
        if profile is not None and isinstance(score, MeasuredSnapshotScore)
        else None
    )
    distributions = (
        {item.metric_id: item for item in population.distributions} if population else {}
    )
    metrics: list[MetricResult] = []
    for metric in result.metrics:
        if isinstance(metric, MeasuredMetric):
            distribution = distributions.get(metric.metric_id)
            calibrated = (
                CalibratedScore(
                    points=float(
                        percentile(metric.raw.value, distribution).quantize(
                            Decimal("0.1"), rounding=ROUND_HALF_UP
                        )
                    ),
                    profile_id=profile.profile_id,
                )
                if distribution is not None and profile is not None
                else None
            )
            metrics.append(metric.model_copy(update={"score": calibrated}))
        else:
            metrics.append(metric)
    return result.model_copy(update={"metrics": tuple(metrics), "score": score})


def score_report(
    report: AnalysisReport,
    profile: CalibrationProfile | None,
    *,
    failure: ScoreUnavailableReason | None = None,
) -> AnalysisReport:
    """Calibrate owned aggregates while preserving source evidence and input order."""
    cohorts = []
    for cohort in report.cohorts:
        current = cohort.current
        scored = _score_result(
            current,
            language=cohort.language,
            provenance=report.provenance,
            profile=profile,
            failure=failure,
        )
        files = tuple(
            _score_result(
                file,
                language=cohort.language,
                provenance=report.provenance,
                profile=profile,
                failure=failure,
            )
            for file in current.files
        )
        cohorts.append(
            cohort.model_copy(update={"current": scored.model_copy(update={"files": files})})
        )
    return report.model_copy(update={"cohorts": tuple(cohorts)})
