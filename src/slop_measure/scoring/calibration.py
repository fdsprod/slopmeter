"""Build reproducible calibration populations from complete raw observations."""

from collections import defaultdict
from typing import Literal, cast

from slop_measure.domain.metrics import (
    MeasuredMetric,
    MetricResult,
    MetricUnit,
    MetricVersion,
    UnavailableMetric,
    UnavailableReason,
)
from slop_measure.domain.reports import AnalysisReport, AnalyzerVersion, SnapshotAnalysis
from slop_measure.domain.scoring import (
    CalibrationProfile,
    CalibrationSettings,
    FilePopulation,
    MetricDistribution,
    MetricWeight,
    ProjectPopulation,
    ReferencePopulation,
    ScoreBand,
    ScoreModel,
)
from slop_measure.domain.source import Cohort

_MetricId = Literal[
    "m2.pattern-verbosity", "m3.clone-verbosity", "m4.erosion", "verbosity.combined"
]
_METRICS: tuple[_MetricId, ...] = (
    "m2.pattern-verbosity",
    "m3.clone-verbosity",
    "m4.erosion",
    "verbosity.combined",
)
_BANDS = ((1, 21), (21, 101), (101, 501), (501, None))
_PopulationKey = tuple[Literal["file", "project"], Cohort, str, int]
_Observation = dict[_MetricId, float]


def _signature(
    report: AnalysisReport,
) -> tuple[AnalyzerVersion, CalibrationSettings, tuple[MetricVersion, ...]]:
    if not isinstance(report.analysis, SnapshotAnalysis):
        raise ValueError("Calibration requires snapshot reports.")
    languages = {cohort.language for cohort in report.cohorts}
    if len(languages) != 1:
        raise ValueError("Calibration reports require exactly one language.")
    analyzer = next(
        (item for item in report.provenance.analyzers if item.language in languages), None
    )
    if (
        analyzer is None
        or not analyzer.rule_set_version
        or not analyzer.clone_normalization_version
    ):
        raise ValueError("Calibration requires rule and clone normalization versions.")
    versions = tuple(
        sorted(
            (item for item in report.provenance.metrics if item.metric_id in _METRICS),
            key=lambda item: item.metric_id,
        )
    )
    if {item.metric_id for item in versions} != set(_METRICS):
        raise ValueError("Calibration requires all snapshot metric versions.")
    return analyzer, CalibrationSettings.from_config(report.provenance.config), versions


def _observation(metrics: tuple[MetricResult, ...]) -> tuple[str, _Observation] | None:
    by_id = {item.metric_id: item for item in metrics}
    combined = by_id.get("verbosity.combined")
    erosion = by_id.get("m4.erosion")
    if not isinstance(combined, MeasuredMetric):
        return None
    if isinstance(erosion, MeasuredMetric):
        model_id = "snapshot"
    elif (
        isinstance(erosion, UnavailableMetric) and erosion.reason is UnavailableReason.NO_FUNCTIONS
    ):
        model_id = "verbosity-only"
    else:
        return None
    values: _Observation = {}
    for metric_id in _METRICS:
        metric = by_id.get(metric_id)
        if isinstance(metric, MeasuredMetric):
            if metric.raw.unit is not MetricUnit.RATIO or not 0 <= metric.raw.value <= 1:
                raise ValueError("Calibration observations require ratios between zero and one.")
            values[metric_id] = metric.raw.value
    return model_id, values


def _populations(
    samples: dict[_PopulationKey, list[_Observation]], min_samples: int
) -> tuple[ReferencePopulation, ...]:
    populations: list[ReferencePopulation] = []
    for (kind, cohort, model_id, band), observations in sorted(samples.items()):
        if len(observations) < min_samples:
            continue
        distributions = tuple(
            MetricDistribution(
                metric_id=metric_id,
                values=tuple(sorted(item[metric_id] for item in observations)),
            )
            for metric_id in _METRICS
            if all(metric_id in item for item in observations)
        )
        if kind == "file":
            lower, upper = _BANDS[band]
            populations.append(
                FilePopulation(
                    cohort=cohort,
                    model_id=model_id,
                    min_sloc=lower,
                    max_sloc=upper,
                    distributions=distributions,
                )
            )
        else:
            populations.append(
                ProjectPopulation(cohort=cohort, model_id=model_id, distributions=distributions)
            )
    return tuple(populations)


def _collect(reports: tuple[AnalysisReport, ...]) -> dict[_PopulationKey, list[_Observation]]:
    samples: dict[_PopulationKey, list[_Observation]] = defaultdict(list)
    for report in reports:
        for cohort in report.cohorts:
            result = cohort.current
            observation = _observation(result.metrics)
            if observation is not None and sum(file.evidence.sloc for file in result.files) > 0:
                model_id, values = observation
                samples[("project", cohort.cohort, model_id, 0)].append(values)
            for file in result.files:
                observation = _observation(file.metrics)
                if file.evidence.sloc == 0 or observation is None:
                    continue
                model_id, values = observation
                band = next(
                    index
                    for index, (lower, upper) in enumerate(_BANDS)
                    if lower <= file.evidence.sloc and (upper is None or file.evidence.sloc < upper)
                )
                samples[("file", cohort.cohort, model_id, band)].append(values)
    return samples


def build_profile(
    reports: tuple[AnalysisReport, ...],
    *,
    profile_id: str,
    corpus_manifest_hash: str,
    min_samples: int = 5,
) -> CalibrationProfile:
    """Keep scope, cohort, model, and file-size populations separate."""
    if (
        not reports
        or isinstance(min_samples, bool)
        or not isinstance(min_samples, int)
        or min_samples < 1
    ):
        raise ValueError("Calibration requires reports and a positive integer sample minimum.")
    identities = tuple(report.analysis.current.model_dump_json() for report in reports)
    if len(identities) != len(set(identities)):
        raise ValueError("Calibration cannot repeat a source identity.")
    signature = _signature(reports[0])
    if any(_signature(report) != signature for report in reports[1:]):
        raise ValueError("Calibration reports have incompatible settings or versions.")
    analyzer, settings, versions = signature
    populations = _populations(_collect(reports), min_samples)
    if not populations:
        raise ValueError("Calibration has no populations with enough complete observations.")
    return CalibrationProfile(
        profile_id=profile_id,
        language=analyzer.language,
        rule_set_version=cast(str, analyzer.rule_set_version),
        clone_normalization_version=cast(str, analyzer.clone_normalization_version),
        metric_versions=versions,
        settings=settings,
        corpus_manifest_hash=corpus_manifest_hash,
        populations=populations,
        score_models=(
            ScoreModel(
                model_id="snapshot",
                eligibility="all-metrics",
                inputs=(
                    MetricWeight(metric_id="verbosity.combined", weight=0.5),
                    MetricWeight(metric_id="m4.erosion", weight=0.5),
                ),
            ),
            ScoreModel(
                model_id="verbosity-only",
                eligibility="no-functions",
                inputs=(MetricWeight(metric_id="verbosity.combined", weight=1),),
            ),
        ),
        bands=(
            ScoreBand(label="low", lower=0),
            ScoreBand(label="moderate", lower=40),
            ScoreBand(label="high", lower=70),
        ),
    )
