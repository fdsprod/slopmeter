"""Execute bounded analysis tasks and retain exact source and tool provenance."""

import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

from evaluation_manifest import Case, Check, EvaluationRun, Manifest, SnapshotRun, read_json

import slop_measure


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def analyzer_identity() -> dict[str, object]:
    """Fingerprint actual installed analyzer files and the runner, not an assumed checkout."""
    package = Path(slop_measure.__file__).resolve().parent
    runner = Path(__file__).resolve().parent
    files = {
        f"analyzer/{path.relative_to(package).as_posix()}": digest(path.read_bytes())
        for path in sorted(package.rglob("*"))
        if path.is_file() and path.suffix in {".py", ".json"}
    }
    files.update(
        {
            f"runner/{path.name}": digest(path.read_bytes())
            for path in sorted(runner.glob("evaluat*.py"))
        }
    )
    return {
        "analyzer_fingerprint": digest(json.dumps(files, sort_keys=True).encode()),
        "analyzer_files": files,
        "analyzer_path": str(package),
        "tool_version": slop_measure.__version__,
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "dependencies": {
            distribution.metadata["Name"]: distribution.version
            for distribution in importlib.metadata.distributions()
            if distribution.metadata["Name"]
        },
    }


def checkout_identity() -> dict[str, object]:
    """Record optional source checkout metadata; exact fingerprints remain authoritative."""
    root = Path(slop_measure.__file__).resolve().parent.parent.parent
    executable = shutil.which("git")
    if executable is None or not (root / ".git").exists():
        return {"state": "unavailable"}
    commands = {
        "revision": ["rev-parse", "HEAD"],
        "status": ["status", "--porcelain=v1", "--", "src", "tools/evaluat*.py"],
        "tracked_diff_sha256": ["diff", "HEAD", "--", "src", "tools/evaluat*.py"],
    }
    result: dict[str, object] = {"state": "available", "root": str(root)}
    try:
        for key, arguments in commands.items():
            process = subprocess.run(  # noqa: S603 - owned analyzer checkout, read-only Git arguments
                [executable, "-c", "core.fsmonitor=false", "-C", str(root), *arguments],
                capture_output=True,
                timeout=2,
                check=True,
            )
            result[key] = (
                digest(process.stdout)
                if key.endswith("sha256")
                else process.stdout.decode("utf-8").strip()
            )
    except (OSError, subprocess.SubprocessError) as error:
        return {"state": "unavailable", "reason": str(error)}
    return result


def run_worker(job: dict[str, object], path: Path, timeout: float) -> dict[str, object]:
    """The child has no executable search path and does not execute target source."""
    save(path, job)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment["PATH"] = ""
    started = time.monotonic()
    try:
        process = subprocess.run(  # noqa: S603 - fixed interpreter and owned static worker
            [
                sys.executable,
                "-I",
                str(Path(__file__).with_name("evaluation_worker.py")),
                str(path),
            ],
            cwd=path.parent,
            env=environment,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"state": "timeout", "seconds": time.monotonic() - started}
    path.with_suffix(".stdout.txt").write_bytes(process.stdout)
    path.with_suffix(".stderr.txt").write_bytes(process.stderr)
    result: dict[str, object] = {
        "state": "passed" if process.returncode == 0 else "error",
        "seconds": time.monotonic() - started,
        "returncode": process.returncode,
    }
    if process.returncode:
        result["reason"] = process.stderr.decode("utf-8", errors="replace")[-4000:]
    return result


def _blob(case: Case, revision: str, source, *, cache: Path, work: Path, options) -> bytes:  # noqa: PLR0913 - explicit source and run locations
    path = cache / source.sha256
    if not path.exists():
        if not options.fetch:
            raise ValueError(f"Offline cache is missing SHA-256 {source.sha256}.")
        temporary = work / f"{source.sha256}.download"
        job: dict[str, object] = {
            "kind": "fetch",
            "url": (
                f"https://raw.githubusercontent.com/{case.repository}/{revision}/"
                f"{quote(source.path, safe='/')}"
            ),
            "destination": str(temporary),
        }
        result = run_worker(job, work / f"{source.sha256}.fetch.json", options.timeout)
        if result["state"] != "passed":
            raise ValueError(f"Source fetch {result['state']}: {source.path}")
        content = temporary.read_bytes()
        if digest(content) != source.sha256:
            raise ValueError(f"Downloaded source SHA-256 mismatch: {source.path}")
        cache.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(content)
    content = path.read_bytes()
    if digest(content) != source.sha256:
        raise ValueError(f"Cached source SHA-256 mismatch: {source.path}")
    return content


def materialize(case: Case, cache: Path, output: Path, options) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for side in ("before", "after"):
        snapshot = getattr(case.snapshots, side)
        root = output / "sources" / case.id / side
        root.mkdir(parents=True)
        for source in snapshot.files:
            content = _blob(
                case,
                snapshot.revision,
                source,
                cache=cache,
                work=output / "downloads",
                options=options,
            )
            target = root / source.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            hashes[f"{case.id}/{side}/{source.path}"] = digest(content)
    return hashes


def _pointer(value: object, pointer: str) -> tuple[bool, object]:
    if not pointer:
        return True, value
    for segment in pointer[1:].split("/"):
        key = segment.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and (
            key == "0" or (key.isascii() and key.isdecimal() and not key.startswith("0"))
        ):
            index = int(key)
            if index >= len(value):
                return False, None
            value = value[index]
        else:
            return False, None
    return True, value


def evaluate_checks(report: object, checks: tuple[Check, ...]) -> list[dict[str, object]]:
    results = []
    for check in checks:
        found, actual = _pointer(report, check.pointer)
        results.append(
            {
                "pointer": check.pointer,
                "expected": check.equals,
                "actual": actual,
                "found": found,
                "passed": found
                and json.dumps(actual, sort_keys=True) == json.dumps(check.equals, sort_keys=True),
            }
        )
    return results


def _diagnostic_errors(report: object) -> bool:
    if not isinstance(report, dict):
        return True
    for diagnostic in report.get("diagnostics", []):
        detail = diagnostic.get("detail", diagnostic)
        if detail.get("severity") == "error":
            return True
    return False


def analyze_run(case: Case, run: EvaluationRun, output: Path, timeout: float) -> dict[str, object]:
    report_path = output / "reports" / case.id / f"{run.id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    sources = output / "sources" / case.id
    job: dict[str, object] = {
        "kind": run.kind,
        "report": str(report_path),
        "before": str(sources / "before"),
        "after": str(sources / "after"),
        "analyzer_path": str(Path(slop_measure.__file__).resolve().parent),
    }
    if isinstance(run, SnapshotRun):
        job.update(command=run.command, source=str(sources / run.snapshot))
    result = run_worker(job, output / "jobs" / case.id / f"{run.id}.json", timeout)
    result.update(case_id=case.id, id=run.id, report=report_path.relative_to(output).as_posix())
    if result["state"] == "passed":
        report = read_json(report_path.read_bytes())
        checks = evaluate_checks(report, run.checks)
        result["checks"] = checks
        if _diagnostic_errors(report):
            result.update(
                state="error", reason="Analysis has error diagnostics; evidence is incomplete."
            )
        elif not all(check["passed"] for check in checks):
            result["state"] = "mismatch"
    return result


def _source_hashes(output: Path) -> dict[str, str]:
    root = output / "sources"
    return {
        path.relative_to(root).as_posix(): digest(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def execute(manifest: Manifest, manifest_bytes: bytes, options) -> tuple[dict[str, object], int]:
    output = options.output.resolve()
    identity = analyzer_identity()
    identity["checkout"] = checkout_identity()
    jobs: list[dict[str, object]] = []
    expected_hashes: dict[str, str] = {}
    issues: list[str] = []
    for case in manifest.cases:
        try:
            expected_hashes.update(materialize(case, options.cache.resolve(), output, options))
        except (OSError, ValueError) as error:
            jobs.extend(
                {"case_id": case.id, "id": run.id, "state": "error", "reason": str(error)}
                for run in case.runs
            )
            continue
        for run in case.runs:
            if analyzer_identity()["analyzer_fingerprint"] != identity["analyzer_fingerprint"]:
                jobs.append(
                    {
                        "case_id": case.id,
                        "id": run.id,
                        "state": "error",
                        "reason": "Analyzer changed during evaluation.",
                    }
                )
                continue
            try:
                jobs.append(analyze_run(case, run, output, options.timeout))
            except (OSError, ValueError) as error:
                jobs.append(
                    {"case_id": case.id, "id": run.id, "state": "error", "reason": str(error)}
                )
    final_identity = analyzer_identity()
    if final_identity["analyzer_fingerprint"] != identity["analyzer_fingerprint"]:
        issues.append("Analyzer changed during evaluation.")
    try:
        if options.manifest.read_bytes() != manifest_bytes:
            issues.append("Manifest changed during evaluation.")
        final_hashes = _source_hashes(output)
        if final_hashes != expected_hashes:
            issues.append("Materialized source changed or materialization was incomplete.")
    except OSError as error:
        final_hashes = None
        issues.append(f"Cannot verify final source or manifest identity: {error}")
    incomplete = bool(issues) or any(job["state"] in {"timeout", "error"} for job in jobs)
    mismatched = any(job["state"] == "mismatch" for job in jobs)
    return {
        "schema_version": 1,
        "state": "incomplete" if incomplete else "complete",
        "jobs": jobs,
        "issues": issues,
        "provenance": {
            **identity,
            "analyzer_fingerprint_after": final_identity["analyzer_fingerprint"],
            "manifest_sha256": digest(manifest_bytes),
            "source_hashes": expected_hashes,
            "source_hashes_after": final_hashes,
            "timeout_seconds": options.timeout,
            "inventory": (
                "Exact manifest files; Git discovery, configured exclusions, "
                "and generated markers disabled."
            ),
        },
    }, 2 if incomplete else (1 if mismatched else 0)
