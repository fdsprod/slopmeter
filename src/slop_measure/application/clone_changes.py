"""Compare retained clone candidates without another detector pass."""

from dataclasses import dataclass

from slop_measure.application._clone_continuity import EditedMembers, connected_groups
from slop_measure.application.change_review import _skipped
from slop_measure.domain.changes import AddedFile, DeletedFile
from slop_measure.domain.clone_changes import (
    ChangedCloneMember,
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


@dataclass(frozen=True)
class _Population:
    group: CloneGroup
    baseline: tuple[CloneOccurrence, ...]
    current: tuple[CloneOccurrence, ...]


def _compatible(old: _Population, new: _Population) -> bool:
    return (old.group.language, old.group.cohort, old.group.normalization_version) == (
        new.group.language,
        new.group.cohort,
        new.group.normalization_version,
    )


def _group_edges(populations: tuple[_Population, ...], matcher: EditedMembers):
    edges = {
        (side, index): set()
        for index, population in enumerate(populations)
        for side, items in enumerate((population.baseline, population.current))
        if items
    }
    for old_index, old in enumerate(populations):
        for new_index, new in enumerate(populations):
            if not old.baseline or not new.current or not _compatible(old, new):
                continue
            same = old_index == new_index
            related = same or (
                old.group.language == "python"
                and any(matcher.relation(x, y)[0] for x in old.baseline for y in new.current)
            )
            if related:
                edges[0, old_index].add((1, new_index))
                edges[1, new_index].add((0, old_index))
    return edges


def _modified_members(
    old, new, matcher: EditedMembers
) -> tuple[list[CloneMemberChange], list[CloneOccurrence], list[CloneOccurrence]]:
    candidates = [(x, y) for x in old for y in new if matcher.relation(x, y)[1]]
    pairs = [
        (x, y)
        for x, y in candidates
        if sum(a == x for a, _ in candidates) == sum(b == y for _, b in candidates) == 1
    ]
    return (
        [ChangedCloneMember(baseline=x, current=y) for x, y in pairs],
        [x for x in old if not any(x == a for a, _ in pairs)],
        [y for y in new if not any(y == b for _, b in pairs)],
    )


def _result(old: _Population | None, new: _Population | None, members) -> CloneGroupChange:
    population = new if new is not None else old
    if population is None:
        raise ValueError("clone continuity requires an observed population")
    group = population.group
    return CloneGroupChange(
        language=group.language,
        cohort=group.cohort,
        normalization_version=group.normalization_version,
        fingerprint=group.fingerprint,
        baseline_fingerprint=old.group.fingerprint if old is not None else None,
        current_fingerprint=new.group.fingerprint if new is not None else None,
        members=tuple(members),
    )


def _ambiguous(populations, component):
    for index in sorted({index for _, index in component}):
        population = populations[index]
        old = population if (0, index) in component else None
        new = population if (1, index) in component else None
        yield _result(
            old,
            new,
            (
                UnresolvedCloneMembers(
                    baseline=old.baseline if old else (),
                    current=new.current if new else (),
                    reason="Edited clone groups have ambiguous split or merge correspondence.",
                ),
            ),
        )


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


def _paired_members(old, new, matcher):
    old_items = old.baseline if old else ()
    new_items = new.current if new else ()
    if old and new and old.group.fingerprint != new.group.fingerprint:
        return _modified_members(old_items, new_items, matcher)
    return _match_members(old_items, new_items, matcher.file_map, *matcher.documents)


def _resolve_groups(populations, matcher, report, inventories, evidence_sides):
    for component in connected_groups(_group_edges(populations, matcher)):
        old = [populations[index] for side, index in component if side == 0]
        new = [populations[index] for side, index in component if side == 1]
        if len(old) > 1 or len(new) > 1:
            yield from _ambiguous(populations, component)
            continue
        before = old[0] if old else None
        after = new[0] if new else None
        members, old_remaining, new_remaining = _paired_members(before, after, matcher)
        members.extend(
            _remaining_members(report, old_remaining, new_remaining, inventories, evidence_sides)
        )
        yield _result(before, after, members)


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
    populations = tuple(
        _Population(
            group,
            _candidate_occurrences(group, old_evidence, before),
            _candidate_occurrences(group, new_evidence, after),
        )
        for _, group in sorted(groups.items())
    )
    return tuple(
        _resolve_groups(
            populations,
            EditedMembers(file_map, before, after),
            report,
            (baseline, current),
            (old_evidence, new_evidence),
        )
    )
