"""Match directory source facts by path, then by exact complete content."""

from collections import defaultdict

from slop_measure.domain.changes import (
    AddedFile,
    DeletedFile,
    FilePair,
    ModifiedFile,
    RenamedFile,
    UnchangedFile,
    UnresolvedFile,
)
from slop_measure.domain.evidence import FileEvidence, ParseState
from slop_measure.domain.source import Cohort, SourceDocument

_Entry = SourceDocument | FileEvidence


def _entries(
    documents: tuple[SourceDocument, ...], unreadable: tuple[FileEvidence, ...]
) -> dict[str, _Entry]:
    if any(file.parse_state is not ParseState.FAILED for file in unreadable):
        raise ValueError("Unreadable comparison files require failed evidence.")
    entries = {item.path.root: item for item in (*documents, *unreadable)}
    if len(entries) != len(documents) + len(unreadable):
        raise ValueError("Comparison source paths must be unique on each side.")
    return entries


def _same_paths(old: dict[str, _Entry], new: dict[str, _Entry]) -> list[FilePair]:
    pairs: list[FilePair] = []
    for path in sorted(old.keys() & new.keys()):
        baseline, current = old[path], new[path]
        if (baseline.language, baseline.cohort) != (current.language, current.cohort):
            continue
        if not isinstance(baseline, SourceDocument) or not isinstance(current, SourceDocument):
            pair = UnresolvedFile(baseline_path=baseline.path, current_path=current.path)
        elif baseline.content == current.content:
            pair = UnchangedFile(baseline_path=baseline.path, current_path=current.path)
        else:
            pair = ModifiedFile(baseline_path=baseline.path, current_path=current.path)
        pairs.append(pair)
        del old[path], new[path]
    return pairs


def _renames(old: dict[str, _Entry], new: dict[str, _Entry]) -> list[FilePair]:
    buckets: dict[tuple[str, Cohort, str], list[SourceDocument]] = defaultdict(list)
    for path in sorted(old):
        item = old[path]
        if isinstance(item, SourceDocument):
            buckets[(item.language, item.cohort, item.content_hash)].append(item)
    pairs: list[FilePair] = []
    for path in sorted(new):
        current = new[path]
        if not isinstance(current, SourceDocument):
            continue
        candidates = buckets[(current.language, current.cohort, current.content_hash)]
        baseline = next((item for item in candidates if item.content == current.content), None)
        if baseline is not None:
            pairs.append(RenamedFile(baseline_path=baseline.path, current_path=current.path))
            candidates.remove(baseline)
            del old[baseline.path.root], new[path]
    return pairs


def _pair_key(pair: FilePair) -> tuple[str, str, str]:
    if isinstance(pair, AddedFile):
        return pair.current_path.root, "", pair.kind
    if isinstance(pair, DeletedFile):
        return pair.baseline_path.root, pair.baseline_path.root, pair.kind
    return pair.current_path.root, pair.baseline_path.root, pair.kind


def match_files(
    baseline: tuple[SourceDocument, ...],
    current: tuple[SourceDocument, ...],
    *,
    baseline_unreadable: tuple[FileEvidence, ...] = (),
    current_unreadable: tuple[FileEvidence, ...] = (),
) -> tuple[FilePair, ...]:
    """Keep each file once, without guessing unreadable content or crossing populations."""
    old, new = _entries(baseline, baseline_unreadable), _entries(current, current_unreadable)
    pairs = _same_paths(old, new)
    pairs.extend(_renames(old, new))
    pairs.extend(DeletedFile(baseline_path=item.path) for item in old.values())
    pairs.extend(AddedFile(current_path=item.path) for item in new.values())
    return tuple(sorted(pairs, key=_pair_key))
