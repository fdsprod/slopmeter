"""Match edited members through explicit file pairs and conservative Python syntax anchors."""

from enum import Enum

from slop_measure.domain.clone_changes import CloneOccurrence
from slop_measure.domain.source import SourceDocument
from slop_measure.languages.python.clone_continuity import CloneSyntaxIndex, anchored_run
from slop_measure.metrics.loc_delta import aligned_line_pairs


class MemberRelation(Enum):
    UNRELATED = "unrelated"
    UNCERTAIN = "uncertain"
    ANCHORED = "anchored"


class EditedMembers:
    def __init__(
        self,
        file_map: dict[str, str],
        baseline: dict[str, SourceDocument],
        current: dict[str, SourceDocument],
    ) -> None:
        self.file_map = file_map
        self.documents = baseline, current
        self.indices: dict[tuple[int, str], CloneSyntaxIndex] = {}
        self.lines: dict[tuple[str, str], dict[int, int]] = {}

    def _syntax(self, side: int, item: CloneOccurrence):
        path = item.member.path.root
        key = side, path
        if key not in self.indices:
            self.indices[key] = CloneSyntaxIndex(self.documents[side][path])
        return self.indices[key].run(item.member.span)

    def relation(self, old: CloneOccurrence, new: CloneOccurrence) -> MemberRelation:
        """Separate absent, uncertain, and structurally anchored correspondence."""
        paths = old.member.path.root, new.member.path.root
        if self.file_map.get(paths[0]) != paths[1]:
            return MemberRelation.UNRELATED
        if paths not in self.lines:
            self.lines[paths] = dict(
                aligned_line_pairs(self.documents[0][paths[0]], self.documents[1][paths[1]])
            )
        line_map = self.lines[paths]
        if not _overlapping_runs(old, new, line_map):
            return MemberRelation.UNRELATED
        before, after = self._syntax(0, old), self._syntax(1, new)
        if before is None or after is None:
            return MemberRelation.UNCERTAIN
        if (before.owner, before.suite) != (after.owner, after.suite):
            return MemberRelation.UNRELATED
        return (
            MemberRelation.ANCHORED
            if anchored_run(before, after, line_map)
            else MemberRelation.UNCERTAIN
        )


def _overlapping_runs(old, new, lines: dict[int, int]) -> bool:
    before, after = old.member.span, new.member.span
    aligned = [value for key, value in lines.items() if before.start_line <= key <= before.end_line]
    if aligned:
        return any(after.start_line <= line <= after.end_line for line in aligned)
    lower = max((value for key, value in lines.items() if key < before.start_line), default=0)
    upper = min(
        (value for key, value in lines.items() if key > before.end_line), default=float("inf")
    )
    return lower < after.start_line <= after.end_line < upper


def connected_groups(edges: dict[tuple[int, int], set[tuple[int, int]]]):
    """Keep ambiguous one-to-many and many-to-one relations together."""
    remaining = set(edges)
    while remaining:
        pending = [min(remaining)]
        found = set()
        while pending:
            item = pending.pop()
            if item in found:
                continue
            found.add(item)
            pending.extend(edges[item] - found)
        remaining.difference_update(found)
        yield tuple(sorted(found))
