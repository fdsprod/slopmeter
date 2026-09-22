"""Compare retained clone candidates without another detector pass."""

from slop_measure.application.change_review import _skipped
from slop_measure.domain.changes import AddedFile, DeletedFile
from slop_measure.domain.clone_changes import (
    CloneGroupChange,
    CloneMemberChange,
    CloneOccurrence,
    IntroducedCloneMember,
    PersistedCloneMember,
    RemovedCloneMember,
    UnresolvedCloneMembers,
)
from slop_measure.domain.evidence import (
    AnalyzedClones,
    CloneGroup,
    CloneMember,
    LanguageEvidence,
    ParseState,
)
from slop_measure.domain.inventory import SourceInventory
from slop_measure.domain.reports import AnalysisReport, ComparisonCohortReport, SourceSide
from slop_measure.metrics.loc_delta import aligned_line_pairs


def _candidate_occurrences(group: CloneGroup, evidence: tuple[LanguageEvidence, ...], documents):
    return tuple(
        CloneOccurrence(
            member=CloneMember(path=item.path, span=item.span, sloc_lines=item.sloc_lines),
            source_sha256=documents[item.path.root].content_hash,
        )
        for language in evidence
        if language.language == group.language
        for item in language.clone_candidates
        if (item.normalization_version, item.fingerprint)
        == (group.normalization_version, group.fingerprint)
        and documents[item.path.root].cohort == group.cohort
    )


def _unassessed(report, side, occurrence, inventory, evidence):
    path = occurrence.member.path
    origin_field, target_field = (
        ("baseline_path", "current_path")
        if side is SourceSide.CURRENT
        else ("current_path", "baseline_path")
    )
    mapped_path = next(
        (
            getattr(change.pair, target_field, None)
            for cohort in report.cohorts
            if isinstance(cohort, ComparisonCohortReport)
            for change in cohort.changes
            if getattr(change.pair, origin_field, None) == path
        ),
        None,
    )
    target_path = mapped_path or path
    files = {file.path: file for language in evidence for file in language.files}
    files.update({file.path: file for file in inventory.failed_files})
    if target_path in files:
        return files[target_path].parse_state is ParseState.FAILED or not any(
            isinstance(outcome, AnalyzedClones) and outcome.path == target_path
            for language in evidence
            for outcome in language.clone_analyses
        )
    counterpart = next(
        file.evidence
        for cohort in report.cohorts
        for result in (cohort.baseline, cohort.current)
        if isinstance(cohort, ComparisonCohortReport)
        for file in result.files
        if file.evidence.path == path
    )
    return _skipped(report, side, counterpart)


def _match_members(old, new, file_map, before, after):
    remaining_old, remaining_new = list(old), list(new)
    result: list[CloneMemberChange] = []
    for old_path, new_path in sorted(file_map.items()):
        left = [x for x in remaining_old if x.member.path.root == old_path]
        right = [x for x in remaining_new if x.member.path.root == new_path]
        line_map = dict(aligned_line_pairs(before.get(old_path), after.get(new_path)))
        pairs = (
            [(left[0], right[0])]
            if len(left) == len(right) == 1
            else [
                (x, y)
                for x in left
                for y in right
                if line_map.get(x.member.span.start_line) == y.member.span.start_line
                and line_map.get(x.member.span.end_line) == y.member.span.end_line
            ]
        )
        for left_item, right_item in pairs:
            result.append(PersistedCloneMember(baseline=left_item, current=right_item))
            remaining_old.remove(left_item)
            remaining_new.remove(right_item)
    return result, remaining_old, remaining_new


def _remaining_members(report, old, new, inventories, evidence_sides):
    result: list[CloneMemberChange] = []
    baseline, current = inventories
    old_evidence, new_evidence = evidence_sides
    for items, side, inventory, evidence in (
        (old, SourceSide.CURRENT, current, new_evidence),
        (new, SourceSide.BASELINE, baseline, old_evidence),
    ):
        for item in list(items):
            if _unassessed(report, side, item, inventory, evidence):
                result.append(
                    UnresolvedCloneMembers(
                        baseline=(item,) if side is SourceSide.CURRENT else (),
                        current=(item,) if side is SourceSide.BASELINE else (),
                        reason="The opposite source has missing or unassessed clone evidence.",
                    )
                )
                items.remove(item)
    if old and new:
        result.append(
            UnresolvedCloneMembers(
                baseline=tuple(old),
                current=tuple(new),
                reason="Clone moves have no unique file correspondence.",
            )
        )
    else:
        result.extend(RemovedCloneMember(baseline=x) for x in old)
        result.extend(IntroducedCloneMember(current=x) for x in new)
    return result


def compare_clones(
    report: AnalysisReport,
    baseline: SourceInventory,
    current: SourceInventory,
    old_evidence: tuple[LanguageEvidence, ...],
    new_evidence: tuple[LanguageEvidence, ...],
) -> tuple[CloneGroupChange, ...]:
    """Track eligible groups and previously unique members with the same normalization."""
    before = {doc.path.root: doc for doc in baseline.documents}
    after = {doc.path.root: doc for doc in current.documents}
    file_map = {
        change.pair.baseline_path.root: change.pair.current_path.root
        for cohort in report.cohorts
        if isinstance(cohort, ComparisonCohortReport)
        for change in cohort.changes
        if not isinstance(change.pair, (AddedFile, DeletedFile))
    }
    groups = {
        (
            g.detail.language,
            g.detail.cohort,
            g.detail.normalization_version,
            g.detail.fingerprint,
        ): g.detail
        for g in report.clone_groups
    }
    result = []
    for key, group in sorted(groups.items()):
        old = _candidate_occurrences(group, old_evidence, before)
        new = _candidate_occurrences(group, new_evidence, after)
        members, old_remaining, new_remaining = _match_members(old, new, file_map, before, after)
        members.extend(
            _remaining_members(
                report,
                old_remaining,
                new_remaining,
                (baseline, current),
                (old_evidence, new_evidence),
            )
        )
        result.append(
            CloneGroupChange(
                language=key[0],
                cohort=key[1],
                normalization_version=key[2],
                fingerprint=key[3],
                members=tuple(members),
            )
        )
    return tuple(result)
