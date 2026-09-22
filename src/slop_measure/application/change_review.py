"""Match existing findings with retained source context and explicit uncertainty."""

from collections import Counter, defaultdict
from collections.abc import Callable, Sequence

from slop_measure.domain.change_review import (
    ChangedPattern,
    ChangeReviewReport,
    ComparisonLimitation,
    IntroducedPattern,
    PatternChange,
    PatternOccurrence,
    PersistedPattern,
    RemovedPattern,
    UnresolvedPatterns,
)
from slop_measure.domain.evidence import (
    CoverageState,
    DiagnosticSeverity,
    FileEvidence,
    ParseState,
    SourceSpan,
)
from slop_measure.domain.inventory import SourceInventory
from slop_measure.domain.metrics import UnavailableMetric, UnavailableReason
from slop_measure.domain.reports import (
    AnalysisReport,
    ComparisonAnalysis,
    ComparisonCohortReport,
    FileResult,
    SourceSide,
)
from slop_measure.domain.source import SourceDocument
from slop_measure.languages.python.change_context import pattern_contexts
from slop_measure.metrics.loc_delta import aligned_line_pairs


def _stable_pairs[T](
    left: Sequence[T], right: Sequence[T], line_map: dict[int, int], span: Callable[[T], SourceSpan]
) -> list[tuple[T, T]]:
    if len(left) == len(right) == 1:
        return [(left[0], right[0])]
    candidates = [
        (old, new)
        for old in left
        for new in right
        if line_map.get(span(old).start_line) == span(new).start_line
        and line_map.get(span(old).end_line) == span(new).end_line
    ]
    old_counts = Counter(id(old) for old, _ in candidates)
    new_counts = Counter(id(new) for _, new in candidates)
    return [
        (old, new) for old, new in candidates if old_counts[id(old)] == new_counts[id(new)] == 1
    ]


def _match_patterns(
    old: tuple[PatternOccurrence, ...],
    new: tuple[PatternOccurrence, ...],
    before: SourceDocument,
    after: SourceDocument,
) -> tuple[PatternChange, ...]:
    old_context = pattern_contexts(before, tuple(item.finding for item in old))
    new_context = pattern_contexts(after, tuple(item.finding for item in new))
    remaining_old, remaining_new = list(old), list(new)
    result: list[PatternChange] = []
    line_map = dict(aligned_line_pairs(before, after))
    # A unique identical statement in the same lexical scope survives relocation.
    keys = sorted({(item.finding.rule_id, *old_context[item.finding]) for item in old})
    for key in keys:
        left = [x for x in remaining_old if (x.finding.rule_id, *old_context[x.finding]) == key]
        right = [x for x in remaining_new if (x.finding.rule_id, *new_context[x.finding]) == key]
        for old_item, new_item in _stable_pairs(
            left, right, line_map, lambda item: item.finding.span
        ):
            result.append(PersistedPattern(baseline=old_item, current=new_item))
            remaining_old.remove(old_item)
            remaining_new.remove(new_item)
    # A single surviving rule site in the same named scope can retain changed evidence.
    keys = sorted({(x.finding.rule_id, old_context[x.finding][0]) for x in remaining_old})
    for rule, scope in keys:
        left = [
            x
            for x in remaining_old
            if (x.finding.rule_id, old_context[x.finding][0]) == (rule, scope)
        ]
        right = [
            x
            for x in remaining_new
            if (x.finding.rule_id, new_context[x.finding][0]) == (rule, scope)
        ]
        if scope and len(left) == len(right) == 1:
            result.append(ChangedPattern(baseline=left[0], current=right[0]))
            remaining_old.remove(left[0])
            remaining_new.remove(right[0])
    rules = sorted({x.finding.rule_id for x in (*remaining_old, *remaining_new)})
    for rule in rules:
        left = tuple(x for x in remaining_old if x.finding.rule_id == rule)
        right = tuple(x for x in remaining_new if x.finding.rule_id == rule)
        if left and right:
            result.append(
                UnresolvedPatterns(
                    baseline=left,
                    current=right,
                    reason="Multiple or rewritten sites lack unique continuity.",
                )
            )
        else:
            result.extend(RemovedPattern(baseline=x) for x in left)
            result.extend(IntroducedPattern(current=x) for x in right)
    return tuple(result)


def _usable(file: FileResult) -> bool:
    return file.evidence.parse_state is ParseState.PARSED and not any(
        isinstance(metric, UnavailableMetric)
        and metric.metric_id == "m2.pattern-verbosity"
        and metric.reason is not UnavailableReason.NO_SOURCE_LINES
        for metric in file.metrics
    )


def _skipped(report: AnalysisReport, side: SourceSide, file: FileEvidence) -> bool:
    if any(
        item.source is side
        and item.detail.severity is DiagnosticSeverity.ERROR
        and item.detail.path is None
        for item in report.diagnostics
    ):
        return True
    if any(
        item.source is side
        and item.detail.state is not CoverageState.SCORED
        and (item.detail.language, item.detail.cohort) == (file.language, file.cohort)
        for item in report.coverage
    ):
        return True
    return any(
        item.source is side and file.path.root.startswith(item.detail.path.root + "/")
        for item in report.excluded_directories
    )


def _uncertain(report: AnalysisReport, left: FileResult | None, right: FileResult | None) -> bool:
    if any(file is not None and not _usable(file) for file in (left, right)):
        return True
    if left is None and right is not None:
        return _skipped(report, SourceSide.BASELINE, right.evidence)
    if right is None and left is not None:
        return _skipped(report, SourceSide.CURRENT, left.evidence)
    return False


def build_change_review(
    report: AnalysisReport,
    baseline: SourceInventory,
    current: SourceInventory,
) -> ChangeReviewReport:
    """Use the comparison's paired files and the exact documents analyzed on each side."""
    if not isinstance(report.analysis, ComparisonAnalysis):
        raise ValueError("Change review requires comparison evidence.")
    cohorts = tuple(item for item in report.cohorts if isinstance(item, ComparisonCohortReport))
    documents = {
        (side, document.path.root): document
        for side, inventory in ((SourceSide.BASELINE, baseline), (SourceSide.CURRENT, current))
        for document in inventory.documents
    }
    files = {
        (side, file.evidence.path.root): file
        for cohort in cohorts
        for side, result in (
            (SourceSide.BASELINE, cohort.baseline),
            (SourceSide.CURRENT, cohort.current),
        )
        for file in result.files
    }
    occurrences: dict[tuple[SourceSide, str], list[PatternOccurrence]] = defaultdict(list)
    for finding in report.findings:
        key = (finding.source, finding.detail.path.root)
        doc = documents[key]
        occurrences[key].append(
            PatternOccurrence(
                finding=finding.detail,
                language=doc.language,
                cohort=doc.cohort,
                source_sha256=doc.content_hash,
            )
        )
    limitations = [
        ComparisonLimitation(
            language=file.evidence.language,
            cohort=file.evidence.cohort,
            path=file.evidence.path,
            reason=f"{side.value} pattern evidence unavailable.",
        )
        for (side, _), file in files.items()
        if not _usable(file)
    ]
    limitations.extend(
        ComparisonLimitation(
            language=item.detail.language,
            cohort=item.detail.cohort,
            reason=f"{item.source.value}: {item.detail.reason or 'unsupported source'}",
        )
        for item in report.coverage
        if item.detail.state is CoverageState.UNSUPPORTED
    )
    changes: list[PatternChange] = []
    for cohort in cohorts:
        for change in cohort.changes:
            pair = change.pair
            old_path = getattr(pair, "baseline_path", None)
            new_path = getattr(pair, "current_path", None)
            old_key = (SourceSide.BASELINE, old_path.root if old_path else "")
            new_key = (SourceSide.CURRENT, new_path.root if new_path else "")
            old, new = tuple(occurrences[old_key]), tuple(occurrences[new_key])
            left, right = files.get(old_key), files.get(new_key)
            if _uncertain(report, left, right):
                limitations.append(
                    ComparisonLimitation(
                        language=cohort.language,
                        cohort=cohort.cohort,
                        path=new_path or old_path,
                        reason="One side has missing or unassessed pattern evidence.",
                    )
                )
                if old or new:
                    changes.append(
                        UnresolvedPatterns(
                            baseline=old,
                            current=new,
                            reason="One side has missing or unassessed pattern evidence.",
                        )
                    )
            elif left is None:
                changes.extend(IntroducedPattern(current=x) for x in new)
            elif right is None:
                changes.extend(RemovedPattern(baseline=x) for x in old)
            else:
                changes.extend(_match_patterns(old, new, documents[old_key], documents[new_key]))
    return ChangeReviewReport(
        analysis=report.analysis,
        provenance=report.provenance,
        patterns=tuple(changes),
        limitations=tuple(limitations),
        coverage=report.coverage,
        diagnostics=report.diagnostics,
        excluded_directories=report.excluded_directories,
    )
