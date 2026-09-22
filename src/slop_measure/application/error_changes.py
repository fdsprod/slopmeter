"""Compare the existing exception detector's outcomes on retained source snapshots."""

from slop_measure.application.change_review import _skipped
from slop_measure.application.error_review import _inspect
from slop_measure.domain.error_changes import (
    ChangedError,
    ErrorChange,
    ErrorCoverage,
    ErrorOccurrence,
    IntroducedError,
    PersistedError,
    RemovedError,
    UnresolvedErrors,
)
from slop_measure.domain.error_review import AnalyzedErrorFile, ErrorFileResult, FailedErrorFile
from slop_measure.domain.evidence import FileEvidence, ParseState
from slop_measure.domain.inventory import SourceInventory
from slop_measure.domain.reports import AnalysisReport, ComparisonCohortReport, SourceSide
from slop_measure.domain.source import SourceDocument
from slop_measure.errors import AnalysisFailure
from slop_measure.metrics.loc_delta import aligned_line_pairs


def _coverage(
    inventory: SourceInventory, side: SourceSide, *, strict: bool
) -> tuple[ErrorCoverage, ...]:
    outcomes = [
        _inspect(document) for document in inventory.documents if document.language == "python"
    ]
    for file in inventory.failed_files:
        if file.language != "python":
            continue
        diagnostic = next(item for item in inventory.diagnostics if item.path == file.path)
        outcomes.append(FailedErrorFile(path=file.path, cohort=file.cohort, diagnostic=diagnostic))
    if strict:
        failure = next((item for item in outcomes if item.state == "failed"), None)
        if failure is not None:
            raise AnalysisFailure(
                f"Strict exception change review failed: {failure.diagnostic.message}"
            )
    return tuple(
        ErrorCoverage(source=side, detail=outcome)
        for outcome in sorted(outcomes, key=lambda item: item.path.root)
    )


def _occurrences(file: ErrorFileResult | None) -> tuple[ErrorOccurrence, ...]:
    if file is None or file.state == "failed":
        return ()
    return tuple(
        ErrorOccurrence(
            path=file.path,
            cohort=file.cohort,
            source_sha256=file.source_sha256,
            symbol=handler.symbol,
            span=handler.span,
            finding=finding,
        )
        for handler in file.handlers
        if handler.state == "analyzed"
        for finding in handler.findings
    )


def _signature(item: ErrorOccurrence) -> tuple[object, ...]:
    finding = item.finding
    return (
        finding.caught,
        finding.fallback_kind,
        finding.fallback.expression,
        tuple(operation.expression for operation in finding.operations),
        tuple(value.expression for value in finding.normal_returns),
    )


def _match_scope(
    old: tuple[ErrorOccurrence, ...], new: tuple[ErrorOccurrence, ...], line_map: dict[int, int]
) -> tuple[ErrorChange, ...]:
    remaining_old, remaining_new = list(old), list(new)
    changes: list[ErrorChange] = []
    signatures = sorted({_signature(item) for item in old}, key=str)
    for signature in signatures:
        left = [item for item in remaining_old if _signature(item) == signature]
        right = [item for item in remaining_new if _signature(item) == signature]
        pairs = (
            [(left[0], right[0])]
            if len(left) == len(right) == 1
            else [
                (before, after)
                for before in left
                for after in right
                if line_map.get(before.span.start_line) == after.span.start_line
                and line_map.get(before.span.end_line) == after.span.end_line
            ]
        )
        for before, after in pairs:
            changes.append(PersistedError(baseline=before, current=after))
            remaining_old.remove(before)
            remaining_new.remove(after)
    if len(remaining_old) == len(remaining_new) == 1:
        changes.append(ChangedError(baseline=remaining_old[0], current=remaining_new[0]))
    elif remaining_old and remaining_new:
        changes.append(
            UnresolvedErrors(
                baseline=tuple(remaining_old),
                current=tuple(remaining_new),
                reason="Multiple exception handlers lack unique correspondence.",
            )
        )
    else:
        changes.extend(RemovedError(baseline=item) for item in remaining_old)
        changes.extend(IntroducedError(current=item) for item in remaining_new)
    return tuple(changes)


def _match_files(
    before: AnalyzedErrorFile,
    after: AnalyzedErrorFile,
    documents: tuple[SourceDocument, SourceDocument],
) -> tuple[ErrorChange, ...]:
    old, new = _occurrences(before), _occurrences(after)
    line_map = dict(aligned_line_pairs(*documents))
    old_symbols = {handler.symbol for handler in before.handlers}
    new_symbols = {handler.symbol for handler in after.handlers}
    unknown = {
        handler.symbol
        for file in (before, after)
        for handler in file.handlers
        if handler.state == "unresolved"
    }
    changes: list[ErrorChange] = []
    for symbol in sorted(old_symbols & new_symbols):
        left = tuple(item for item in old if item.symbol == symbol)
        right = tuple(item for item in new if item.symbol == symbol)
        if not left and not right:
            continue
        if symbol in unknown:
            changes.append(
                UnresolvedErrors(
                    baseline=left,
                    current=right,
                    reason="A corresponding exception handler is outside assessed coverage.",
                )
            )
        else:
            changes.extend(_match_scope(left, right, line_map))
    left = tuple(item for item in old if item.symbol not in new_symbols)
    right = tuple(item for item in new if item.symbol not in old_symbols)
    if (left or right) and old_symbols - new_symbols and new_symbols - old_symbols:
        changes.append(
            UnresolvedErrors(
                baseline=left,
                current=right,
                reason="Changed exception handler scopes lack unique correspondence.",
            )
        )
    else:
        changes.extend(RemovedError(baseline=item) for item in left)
        changes.extend(IntroducedError(current=item) for item in right)
    return tuple(changes)


def _missing_assessment(
    report: AnalysisReport, side: SourceSide, opposite: ErrorFileResult | None
) -> bool:
    if opposite is None:
        return False
    return _skipped(
        report,
        side,
        FileEvidence(
            path=opposite.path,
            language="python",
            cohort=opposite.cohort,
            sloc=0,
            sloc_lines=(),
            parse_state=ParseState.PARSED,
        ),
    )


def compare_errors(
    report: AnalysisReport, baseline: SourceInventory, current: SourceInventory
) -> tuple[tuple[ErrorChange, ...], tuple[ErrorCoverage, ...]]:
    """Retain all handler assessments and never turn unavailable evidence into a fix."""
    strict = report.provenance.config.strict
    coverage = (
        *_coverage(baseline, SourceSide.BASELINE, strict=strict),
        *_coverage(current, SourceSide.CURRENT, strict=strict),
    )
    outcomes = {(item.source, item.detail.path.root): item.detail for item in coverage}
    documents = {
        (side, document.path.root): document
        for side, inventory in ((SourceSide.BASELINE, baseline), (SourceSide.CURRENT, current))
        for document in inventory.documents
    }
    changes: list[ErrorChange] = []
    for cohort in report.cohorts:
        if not isinstance(cohort, ComparisonCohortReport) or cohort.language != "python":
            continue
        for change in cohort.changes:
            pair = change.pair
            old_path, new_path = (
                getattr(pair, "baseline_path", None),
                getattr(pair, "current_path", None),
            )
            old_key = (SourceSide.BASELINE, old_path.root if old_path else "")
            new_key = (SourceSide.CURRENT, new_path.root if new_path else "")
            before, after = outcomes.get(old_key), outcomes.get(new_key)
            old, new = _occurrences(before), _occurrences(after)
            if not old and not new:
                continue
            uncertain = (
                (before is not None and before.state == "failed")
                or (after is not None and after.state == "failed")
                or (before is None and _missing_assessment(report, SourceSide.BASELINE, after))
                or (after is None and _missing_assessment(report, SourceSide.CURRENT, before))
            )
            if uncertain:
                changes.append(
                    UnresolvedErrors(
                        baseline=old,
                        current=new,
                        reason="One side has missing or failed exception analysis.",
                    )
                )
            elif before is None:
                changes.extend(IntroducedError(current=item) for item in new)
            elif after is None:
                changes.extend(RemovedError(baseline=item) for item in old)
            elif before.state == "analyzed" and after.state == "analyzed":
                changes.extend(
                    _match_files(before, after, (documents[old_key], documents[new_key]))
                )
    return tuple(changes), coverage
