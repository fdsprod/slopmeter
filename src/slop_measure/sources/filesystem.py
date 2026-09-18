"""Discover source files without importing them or changing the checkout."""

import os
import shutil
import subprocess
from collections import Counter
from fnmatch import fnmatchcase
from functools import cache
from pathlib import Path, PurePosixPath

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import (
    Coverage,
    CoverageState,
    Diagnostic,
    DiagnosticSeverity,
    FileEvidence,
    ParseState,
)
from slop_measure.domain.inventory import SourceInventory
from slop_measure.domain.source import Cohort, DirectorySourceIdentity, ProjectPath, SourceDocument
from slop_measure.languages.registry import LanguageRegistry


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    segments = tuple(path.split("/"))

    @cache
    def match(parts: tuple[str, ...], candidate: tuple[str, ...]) -> bool:
        if not parts:
            return not candidate
        if parts[0] == "**":
            return match(parts[1:], candidate) or bool(candidate and match(parts, candidate[1:]))
        return bool(
            candidate and fnmatchcase(candidate[0], parts[0]) and match(parts[1:], candidate[1:])
        )

    return any(
        match(tuple(pattern.replace("\\", "/").split("/")), segments) for pattern in patterns
    )


def _git_files(root: Path) -> set[str] | None:
    executable = shutil.which("git")
    if executable is None:
        return None
    environment = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}
    command = [executable, "-c", "core.fsmonitor=false", "-C", str(root)]
    probe = subprocess.run(  # noqa: S603 - fixed read-only Git arguments
        [*command, "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        env=environment,
        check=False,
    )
    if probe.returncode != 0 or probe.stdout.strip() != b"true":
        return None
    result = subprocess.run(  # noqa: S603 - fixed read-only Git arguments
        [*command, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "."],
        capture_output=True,
        env=environment,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("Git source inventory failed")
    return {os.fsdecode(path) for path in result.stdout.split(b"\0") if path}


class FilesystemSourceProvider:
    """Inventory one resolved directory under explicit analysis settings."""

    def __init__(self, root: Path, config: AnalysisConfig, registry: LanguageRegistry) -> None:
        self.root = root.resolve()
        self.config = config
        self.registry = registry

    def identity(self) -> DirectorySourceIdentity:
        """Return the resolved identity without reading or changing source files."""
        return DirectorySourceIdentity(root=self.root)

    def _walk_error(self, error: OSError) -> Diagnostic:
        location = None
        if error.filename:
            try:
                relative = Path(error.filename).relative_to(self.root).as_posix()
                if relative != ".":
                    location = ProjectPath(relative)
            except ValueError:
                pass
        return Diagnostic(
            severity=DiagnosticSeverity.ERROR,
            code="source.read-error",
            message=f"Cannot read source directory: {error.strerror or type(error).__name__}",
            path=location,
        )

    def _paths(self, diagnostics: list[Diagnostic]) -> list[Path]:
        paths: list[Path] = []
        for directory, directories, filenames in os.walk(
            self.root,
            followlinks=False,
            onerror=lambda error: diagnostics.append(self._walk_error(error)),
        ):
            parent = Path(directory)
            directories[:] = [
                name
                for name in directories
                if name != ".git"
                and not (parent / name).is_symlink()
                and not (parent / name).is_junction()
            ]
            paths.extend(parent / name for name in filenames if name != ".git")
        return sorted(paths, key=lambda path: path.relative_to(self.root).as_posix())

    def _excluded_reason(self, path: Path, relative: str, git_files: set[str] | None) -> str | None:
        if path.is_symlink():
            return "symlink"
        if _matches(relative, self.config.exclusions):
            return "configured exclusion"
        if git_files is not None and relative not in git_files:
            return "git ignored"
        return None

    def inventory(self) -> SourceInventory:
        """Read eligible source bytes and report every skipped file population."""
        if not self.root.is_dir():
            raise ValueError(f"source root must be an existing directory: {self.root}")
        builder = _InventoryBuilder(self)
        git_files = _git_files(self.root)
        for path in self._paths(builder.diagnostics):
            builder.add(path, git_files)
        return builder.finish()


class _InventoryBuilder:
    """Collect one inventory without keeping state on a reusable provider."""

    def __init__(self, provider: FilesystemSourceProvider) -> None:
        self.provider = provider
        self.documents: list[SourceDocument] = []
        self.failed_files: list[FileEvidence] = []
        self.diagnostics: list[Diagnostic] = []
        self.skipped: Counter[tuple[CoverageState, Cohort, str, str]] = Counter()

    def add(self, path: Path, git_files: set[str] | None) -> None:
        relative = path.relative_to(self.provider.root).as_posix()
        project_path = ProjectPath(relative)
        adapter = self.provider.registry.for_path(project_path)
        language = (
            adapter.language_id
            if adapter
            else PurePosixPath(relative).suffix.lstrip(".") or "unknown"
        )
        config = self.provider.config
        cohort = Cohort.TEST if _matches(relative, config.test_patterns) else Cohort.PRODUCTION
        reason = self.provider._excluded_reason(path, relative, git_files)
        if reason is not None:
            self.skipped[CoverageState.EXCLUDED, cohort, language, reason] += 1
        elif adapter is None:
            self.skipped[CoverageState.UNSUPPORTED, cohort, language, "no language adapter"] += 1
        elif cohort is Cohort.PRODUCTION and not _matches(relative, config.production_patterns):
            self.skipped[
                CoverageState.EXCLUDED, cohort, language, "outside configured cohorts"
            ] += 1
        else:
            self.read(path, project_path, language, cohort)

    def read(self, path: Path, project_path: ProjectPath, language: str, cohort: Cohort) -> None:
        try:
            content = path.read_bytes()
        except OSError as error:
            self.failed_files.append(
                FileEvidence(
                    path=project_path,
                    language=language,
                    cohort=cohort,
                    sloc=0,
                    sloc_lines=(),
                    parse_state=ParseState.FAILED,
                )
            )
            self.diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    code="source.read-error",
                    message=f"Cannot read source file: {error.strerror or type(error).__name__}",
                    path=project_path,
                )
            )
            return
        if any(
            marker.encode("utf-8") in content for marker in self.provider.config.generated_markers
        ):
            self.skipped[CoverageState.EXCLUDED, cohort, language, "generated marker"] += 1
            return
        self.documents.append(
            SourceDocument(path=project_path, content=content, language=language, cohort=cohort)
        )

    def finish(self) -> SourceInventory:
        coverage = tuple(
            Coverage(
                state=state,
                cohort=cohort,
                language=language,
                reason=reason,
                file_count=count,
                sloc=0,
            )
            for (state, cohort, language, reason), count in sorted(self.skipped.items())
        )
        return SourceInventory(
            documents=tuple(self.documents),
            coverage=coverage,
            failed_files=tuple(self.failed_files),
            diagnostics=tuple(self.diagnostics),
        )
