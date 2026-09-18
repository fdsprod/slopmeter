"""Read pinned Git objects and rename metadata without changing a checkout."""

import os
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import Coverage, CoverageState
from slop_measure.domain.inventory import SourceInventory
from slop_measure.domain.source import (
    Cohort,
    DirectorySourceIdentity,
    GitSourceIdentity,
    ProjectPath,
    SourceDocument,
)
from slop_measure.errors import InvalidSource
from slop_measure.languages.registry import LanguageRegistry
from slop_measure.sources.filesystem import _matches

_OVERRIDES = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    }
)
_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def _run(root: Path, *arguments: str) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        raise InvalidSource("Git is not installed or is not available on PATH.")
    environment = {key: value for key, value in os.environ.items() if key not in _OVERRIDES}
    environment.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_NO_LAZY_FETCH": "1",
        }
    )
    try:
        result = subprocess.run(  # noqa: S603 - resolved executable and read-only Git argument lists
            [executable, "-c", "core.fsmonitor=false", "-C", str(root), *arguments],
            capture_output=True,
            env=environment,
            check=False,
        )
    except OSError as error:
        raise InvalidSource(f"Cannot read Git source: {error}") from error
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise InvalidSource(f"Cannot read Git source: {detail or 'Git command failed.'}")
    return result.stdout


def _root(root: Path) -> Path:
    resolved = root.resolve()
    top = Path(
        os.fsdecode(_run(resolved, "rev-parse", "--show-toplevel").rstrip(b"\r\n"))
    ).resolve()
    if top != resolved:
        raise InvalidSource("Git source root must be the repository's top-level worktree.")
    return resolved


def _revision(root: Path, revision: str) -> str:
    if not revision.strip():
        raise InvalidSource("Git source revision must be nonempty.")
    try:
        resolved = _run(
            root, "rev-parse", "--verify", "--end-of-options", revision + "^{commit}"
        ).strip()
    except InvalidSource as error:
        raise InvalidSource(f"Cannot resolve Git revision {revision!r}: {error}") from error
    value = resolved.decode("ascii")
    if _OBJECT_ID.fullmatch(value) is None:
        raise InvalidSource("Git did not resolve a complete commit identity.")
    return value


@dataclass(frozen=True)
class _Entry:
    path: ProjectPath
    mode: str
    object_id: str


def _tree(root: Path, revision: str) -> tuple[_Entry, ...]:
    entries = []
    output = _run(root, "ls-tree", "-r", "--full-tree", "-z", revision)
    try:
        for record in output.split(b"\0"):
            if not record:
                continue
            metadata, path = record.split(b"\t", 1)
            mode, _, object_id = metadata.decode("ascii").split(" ")
            if _OBJECT_ID.fullmatch(object_id) is None:
                raise ValueError("Invalid Git tree object identity.")
            entries.append(_Entry(ProjectPath(os.fsdecode(path)), mode, object_id))
    except (UnicodeError, ValueError) as error:
        raise InvalidSource("Git returned an invalid source tree.") from error
    return tuple(sorted(entries, key=lambda item: item.path.root))


class GitSourceProvider:
    """Pin a commit once and apply the same source policy as directory inventory."""

    def __init__(
        self, root: Path, revision: str, config: AnalysisConfig, registry: LanguageRegistry
    ) -> None:
        resolved = _root(root)
        self._identity = GitSourceIdentity(root=resolved, revision=_revision(resolved, revision))
        self.config = config
        self.registry = registry

    def identity(self) -> GitSourceIdentity:
        """Return the complete commit identity pinned at construction."""
        return self._identity

    def inventory(self) -> SourceInventory:
        """Read eligible committed bytes, independent of dirty or untracked files."""
        builder = _GitInventory(self)
        for entry in _tree(self._identity.root, self._identity.revision):
            builder.add(entry)
        return builder.finish()


class _GitInventory:
    def __init__(self, provider: GitSourceProvider) -> None:
        self.provider = provider
        self.documents: list[SourceDocument] = []
        self.skipped: Counter[tuple[CoverageState, Cohort, str, str]] = Counter()

    def _excluded(self, entry: _Entry) -> str | None:
        if entry.mode == "120000":
            return "symlink"
        if entry.mode == "160000":
            return "submodule"
        if entry.mode not in {"100644", "100755"}:
            raise InvalidSource(f"Unsupported Git source mode: {entry.mode}")
        if _matches(entry.path.root, self.provider.config.exclusions):
            return "configured exclusion"
        return None

    def add(self, entry: _Entry) -> None:
        relative = entry.path.root
        config = self.provider.config
        adapter = self.provider.registry.for_path(entry.path)
        language = (
            adapter.language_id
            if adapter
            else PurePosixPath(relative).suffix.lstrip(".") or "unknown"
        )
        cohort = Cohort.TEST if _matches(relative, config.test_patterns) else Cohort.PRODUCTION
        reason = self._excluded(entry)
        if reason is not None:
            self.skipped[CoverageState.EXCLUDED, cohort, language, reason] += 1
        elif adapter is None:
            self.skipped[CoverageState.UNSUPPORTED, cohort, language, "no language adapter"] += 1
        elif cohort is Cohort.PRODUCTION and not _matches(relative, config.production_patterns):
            self.skipped[
                CoverageState.EXCLUDED, cohort, language, "outside configured cohorts"
            ] += 1
        else:
            content = _run(self.provider.identity().root, "cat-file", "blob", entry.object_id)
            if any(marker.encode("utf-8") in content for marker in config.generated_markers):
                self.skipped[CoverageState.EXCLUDED, cohort, language, "generated marker"] += 1
            else:
                self.documents.append(
                    SourceDocument(
                        path=entry.path, content=content, language=language, cohort=cohort
                    )
                )

    def finish(self) -> SourceInventory:
        return SourceInventory(
            documents=tuple(self.documents),
            coverage=tuple(
                Coverage(
                    state=state,
                    cohort=cohort,
                    language=language,
                    reason=reason,
                    file_count=count,
                    sloc=0,
                )
                for (state, cohort, language, reason), count in sorted(self.skipped.items())
            ),
        )


def rename_pairs(
    baseline: GitSourceIdentity, current: GitSourceIdentity | DirectorySourceIdentity
) -> tuple[tuple[ProjectPath, ProjectPath], ...]:
    """Read Git rename metadata only when both source states share a repository root."""
    if baseline.root.resolve() != current.root.resolve():
        return ()
    root = _root(baseline.root)
    revisions = [_revision(root, baseline.revision)]
    if isinstance(current, GitSourceIdentity):
        revisions.append(_revision(root, current.revision))
    fields = _run(
        root,
        "diff",
        "-M",
        "--name-status",
        "-z",
        "--no-ext-diff",
        "--no-textconv",
        *revisions,
        "--",
    ).split(b"\0")
    pairs: list[tuple[ProjectPath, ProjectPath]] = []
    index = 0
    try:
        while index < len(fields) and fields[index]:
            status = fields[index]
            count = 3 if status[:1] in {b"R", b"C"} else 2
            if index + count > len(fields) or not fields[index + count - 1]:
                raise ValueError("Incomplete Git rename record.")
            if status.startswith(b"R"):
                pairs.append(
                    (
                        ProjectPath(os.fsdecode(fields[index + 1])),
                        ProjectPath(os.fsdecode(fields[index + 2])),
                    )
                )
            index += count
    except ValueError as error:
        raise InvalidSource("Git returned invalid rename metadata.") from error
    return tuple(sorted(pairs, key=lambda pair: (pair[0].root, pair[1].root)))
