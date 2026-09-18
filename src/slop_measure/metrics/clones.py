"""Group normalized owned blocks and retain maximal useful clone evidence."""

from slop_measure.domain.evidence import (
    CloneCandidate,
    CloneGroup,
    CloneMember,
    FileEvidence,
    clone_candidate_key,
    clone_member_key,
    has_distinct_clone_instances,
    validate_clone_member,
)
from slop_measure.domain.source import Cohort


def _size(group: CloneGroup) -> int:
    return sum(len(member.sloc_lines) for member in group.members)


def _encloses(outer: CloneMember, inner: CloneMember) -> bool:
    return (
        outer.path == inner.path
        and outer.span.start_line <= inner.span.start_line
        and outer.span.end_line >= inner.span.end_line
    )


def _contained(inner: CloneGroup, outer: CloneGroup) -> bool:
    if (
        inner.language != outer.language
        or inner.cohort is not outer.cohort
        or inner.normalization_version != outer.normalization_version
        or len(inner.members) > len(outer.members)
        or _size(inner) >= _size(outer)
    ):
        return False
    by_path: dict[str, list[tuple[int, CloneMember]]] = {}
    for index, member in enumerate(outer.members):
        by_path.setdefault(member.path.root, []).append((index, member))
    choices = tuple(
        tuple(
            index for index, member in by_path.get(child.path.root, ()) if _encloses(member, child)
        )
        for child in inner.members
    )
    assigned: dict[int, int] = {}

    def assign(child: int, visited: set[int]) -> bool:
        for parent in choices[child]:
            if parent in visited:
                continue
            visited.add(parent)
            previous = assigned.get(parent)
            if previous is None or assign(previous, visited):
                assigned[parent] = child
                return True
        return False

    return all(assign(index, set()) for index in range(len(inner.members)))


def _order(group: CloneGroup) -> tuple[str, str, str, str, tuple[tuple[str, int, int], ...]]:
    return (
        group.language,
        group.cohort.value,
        group.normalization_version,
        group.fingerprint,
        tuple(clone_member_key(member) for member in group.members),
    )


def group_clones(
    files: tuple[FileEvidence, ...], candidates: tuple[CloneCandidate, ...]
) -> tuple[CloneGroup, ...]:
    """Match tokens within each population, then collapse fully contained groups."""
    owners = {file.path.root: file for file in files}
    if len(owners) != len(files):
        raise ValueError("clone grouping requires unique file paths")
    partitions: dict[tuple[str, Cohort, str, tuple[str, ...]], list[CloneCandidate]] = {}
    identities: set[tuple[tuple[str, int, int], str, tuple[str, ...]]] = set()
    for candidate in candidates:
        file = owners.get(candidate.path.root)
        if file is None:
            raise ValueError("clone candidate has no owning file")
        validate_clone_member(file, candidate)
        identity = clone_candidate_key(candidate)
        if identity in identities:
            raise ValueError("duplicate clone candidate identity")
        identities.add(identity)
        key = (
            file.language,
            file.cohort,
            candidate.normalization_version,
            candidate.normalized_tokens,
        )
        partitions.setdefault(key, []).append(candidate)
    groups = []
    for (language, cohort, version, _tokens), instances in partitions.items():
        members = tuple(
            CloneMember(path=item.path, span=item.span, sloc_lines=item.sloc_lines)
            for item in sorted(instances, key=clone_member_key)
        )
        if not has_distinct_clone_instances(members):
            continue
        groups.append(
            CloneGroup(
                language=language,
                cohort=cohort,
                normalization_version=version,
                fingerprint=instances[0].fingerprint,
                members=members,
            )
        )
    kept: list[CloneGroup] = []
    for group in sorted(groups, key=lambda item: (-_size(item), _order(item))):
        if not any(_contained(group, larger) for larger in kept):
            kept.append(group)
    return tuple(sorted(kept, key=_order))
