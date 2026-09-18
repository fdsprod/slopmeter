"""Build a calibration profile from verified, already-cached source repositories."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.domain.reports import AnalysisReport
from slop_measure.domain.scoring import CalibrationSettings
from slop_measure.domain.source import ProjectPath
from slop_measure.scoring.calibration import build_profile

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_Name = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]


class _Project(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: _Name
    repository: _Text
    revision: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
    license: _Text
    license_file: ProjectPath
    tag: _Text
    release_date: _Text
    production_patterns: tuple[_Text, ...]
    test_patterns: tuple[_Text, ...]
    exclusions: tuple[_Text, ...]

    @model_validator(mode="after")
    def validate_patterns(self) -> Self:
        for pattern in (*self.production_patterns, *self.test_patterns, *self.exclusions):
            path = PurePosixPath(pattern.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or ":" in pattern:
                raise ValueError("Corpus patterns must stay inside their repository.")
        return self


class _Manifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"]
    profile_id: _Name
    language: Literal["python"]
    min_samples: Annotated[int, Field(gt=0, strict=True)] = 5
    settings: CalibrationSettings
    projects: Annotated[tuple[_Project, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_projects(self) -> Self:
        names = {project.name.casefold() for project in self.projects}
        repositories = {
            project.repository.rstrip("/").removesuffix(".git") for project in self.projects
        }
        if len(names) != len(self.projects) or len(repositories) != len(self.projects):
            raise ValueError("Corpus project names and repositories must be unique.")
        return self


def _git(root: Path, *arguments: str) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        raise ValueError("Git is required to verify the cached corpus.")
    result = subprocess.run(  # noqa: S603 - resolved Git executable and fixed read-only arguments
        [executable, "-c", "core.fsmonitor=false", "-C", str(root), *arguments],
        capture_output=True,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"},
        check=False,
    )
    if result.returncode:
        raise ValueError(f"Cannot verify cached repository {root.name}.")
    return result.stdout


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Corpus paths must stay inside their repository.")
    return path


def _verify(cache: Path, project: _Project) -> Path:
    root = _inside(cache, project.name)
    if not root.is_dir():
        raise ValueError(f"Cached repository {project.name} does not exist.")
    if _git(root, "rev-parse", "HEAD").decode().strip() != project.revision:
        raise ValueError(f"Cached repository {project.name} has the wrong revision.")
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all").strip():
        raise ValueError(f"Cached repository {project.name} is not clean.")
    if not _inside(root, project.license_file.root).is_file():
        raise ValueError(f"Cached repository {project.name} has no declared license file.")
    return root


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _inventory(root: Path, project: _Project, report: AnalysisReport) -> dict[str, object]:
    analyzed = {
        file.evidence.path.root: file.evidence.cohort.value
        for cohort in report.cohorts
        for file in cohort.current.files
    }
    records: list[dict[str, str]] = []
    paths = sorted(
        os.fsdecode(path) for path in _git(root, "ls-files", "--cached", "-z").split(b"\0") if path
    )
    for relative in paths:
        path = _inside(root, relative)
        record = {
            "path": relative,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "status": "analyzed" if relative in analyzed else "excluded-or-unselected",
        }
        if relative in analyzed:
            record["cohort"] = analyzed[relative]
        records.append(record)
    return {
        "project": project.name,
        "repository": project.repository,
        "revision": project.revision,
        "license": project.license,
        "license_file": project.license_file.root,
        "files": records,
    }


def _config(manifest: _Manifest, project: _Project) -> AnalysisConfig:
    return AnalysisConfig.model_validate(
        {
            **manifest.settings.model_dump(),
            "production_patterns": project.production_patterns,
            "test_patterns": project.test_patterns,
            "exclusions": project.exclusions,
            "calibration_profile": "__raw__",
        }
    )


def _build(manifest_path: Path, cache: Path, output: Path, evidence_dir: Path | None) -> None:
    raw_manifest = manifest_path.read_bytes()
    manifest = _Manifest.model_validate(tomllib.loads(raw_manifest.decode("utf-8")))
    evidence = (evidence_dir or cache / "evidence" / manifest.profile_id).resolve()
    companion = output.parent / f"{manifest.profile_id}.corpus.toml"
    projects = tuple(sorted(manifest.projects, key=lambda item: item.name))
    verified = tuple((project, _verify(cache, project)) for project in projects)
    destinations = (output, companion, evidence)
    if output in (manifest_path, companion) or any(
        destination.is_relative_to(root) for destination in destinations for _, root in verified
    ):
        raise ValueError("Calibration output must stay outside cached source repositories.")
    reports: list[AnalysisReport] = []
    artifacts: dict[Path, bytes] = {}
    for project, root in verified:
        report = scan(
            SnapshotRequest(
                target=DirectorySourceReference(root=root), config=_config(manifest, project)
            )
        )
        reports.append(report)
        artifacts[evidence / f"{project.name}.report.json"] = _json(report.model_dump(mode="json"))
        artifacts[evidence / f"{project.name}.inventory.json"] = _json(
            _inventory(root, project, report)
        )
    profile = build_profile(
        tuple(reports),
        profile_id=manifest.profile_id,
        corpus_manifest_hash=hashlib.sha256(raw_manifest).hexdigest(),
        min_samples=manifest.min_samples,
    )
    artifacts[companion] = raw_manifest
    # Write the profile last so rejected sources cannot leave a usable-looking profile.
    artifacts[output] = _json(profile.model_dump(mode="json"))
    for path, content in artifacts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def main(argv: list[str] | None = None) -> int:
    """Verify, measure, and record the manifest's fixed corpus without target execution."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        _build(
            args.manifest.resolve(), args.cache.resolve(), args.output.resolve(), args.evidence_dir
        )
    except (OSError, ValueError) as error:
        print(f"Calibration failed: {error}", file=sys.stderr)
        return 2
    print(f"Wrote calibration profile {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
