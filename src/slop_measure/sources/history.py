"""Read bounded raw first-parent ancestry using the existing offline Git runner."""

from dataclasses import dataclass
from pathlib import Path

from slop_measure.domain.history import (
    CompleteHistory,
    HistoryRequest,
    HistoryTraversal,
    PartialHistory,
)
from slop_measure.domain.source import GitSourceIdentity
from slop_measure.errors import InvalidSource
from slop_measure.sources.git import _OBJECT_ID, _revision, _root, _run


@dataclass(frozen=True)
class HistoryCommit:
    revision: str
    parents: tuple[str, ...]
    timestamp: int


@dataclass(frozen=True)
class HistoryRange:
    start: GitSourceIdentity
    end: GitSourceIdentity
    traversal: HistoryTraversal
    commits: tuple[HistoryCommit, ...]


def _commit(root: Path, revision: str) -> HistoryCommit:
    headers = _run(root, "cat-file", "commit", revision).split(b"\n\n", 1)[0].splitlines()
    try:
        parents = tuple(line[7:].decode("ascii") for line in headers if line.startswith(b"parent "))
        if any(_OBJECT_ID.fullmatch(parent) is None for parent in parents):
            raise ValueError("invalid parent identity")
        committer = next(line for line in headers if line.startswith(b"committer "))
        timestamp = int(committer.rsplit(b" ", 2)[1])
    except (UnicodeError, ValueError, StopIteration) as error:
        raise InvalidSource("Git returned invalid commit metadata.") from error
    return HistoryCommit(revision, parents, timestamp)


def read_history_range(request: HistoryRequest) -> HistoryRange:
    """Preserve actual parent headers even when Git traversal stops at a shallow tip."""
    root = _root(request.root)
    start = GitSourceIdentity(root=root, revision=_revision(root, request.start))
    end = GitSourceIdentity(root=root, revision=_revision(root, request.end))
    pending = end.revision
    commits = []
    traversal: HistoryTraversal = CompleteHistory()
    while pending != start.revision:
        if len(commits) == request.max_commits:
            traversal = PartialHistory(reason="commit-limit", boundary_commit=pending)
            break
        commit = _commit(root, pending)
        if not commit.parents:
            raise InvalidSource("History start is not on the end revision's first-parent chain.")
        try:
            _run(root, "cat-file", "-e", commit.parents[0])
        except InvalidSource:
            traversal = PartialHistory(reason="missing-parent", boundary_commit=pending)
            break
        commits.append(commit)
        pending = commit.parents[0]
    return HistoryRange(start, end, traversal, tuple(reversed(commits)))
