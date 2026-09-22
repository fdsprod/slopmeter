"""Pinned public evaluations retain evidence and fail closed without executing subjects."""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.xfail(
    strict=True, reason="Evaluation runner contract precedes implementation"
)

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tools" / "evaluate.py"
ERROR = (
    "def fetch(client):\n    try:\n        result = client.read()\n"
    "    except OSError:\n        return []\n    return result\n"
)
DERIVED = (
    "def work():\n    items = [1]\n    count = len(items)\n    items.append(2)\n    return count\n"
)


def _snapshot(cache: Path, revision: str, files: dict[str, str]) -> dict:
    records = []
    for name, source in files.items():
        blob = source.encode("utf-8")
        digest = hashlib.sha256(blob).hexdigest()
        (cache / digest).write_bytes(blob)
        records.append({"path": name, "sha256": digest})
    return {"revision": revision * 40, "files": records}


def _case(cache: Path, *, before: str = ERROR, after: str | None = None) -> dict:
    return {
        "id": "fallback-fix",
        "repository": "example/offline-evaluation-fixture",
        "label": "supported-positive",
        "rationale": "Synthetic evaluation-runner control, not independent public evidence.",
        "evidence_url": "https://example.com/evaluation-control",
        "snapshots": {
            "before": _snapshot(cache, "a", {"subject.py": before}),
            "after": _snapshot(
                cache, "b", {"subject.py": after or before.replace("return []", "raise")}
            ),
        },
        "runs": [_run("before", "errors", "/summary/findings", 1)],
    }


def _run(snapshot: str, command: str, pointer: str, expected: object) -> dict:
    return {
        "id": f"{command}-{snapshot}",
        "kind": "snapshot",
        "command": command,
        "snapshot": snapshot,
        "checks": [{"pointer": pointer, "equals": expected}],
    }


def _invoke(
    tmp_path: Path, case: dict, *extra: str, manifest_override: dict | None = None
) -> subprocess.CompletedProcess[str]:
    assert RUNNER.is_file(), "The public evaluation CLI must exist."
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(manifest_override or {"schema_version": 1, "cases": [case]}), encoding="utf-8"
    )
    return subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(RUNNER),
            "--manifest",
            str(manifest),
            "--cache",
            str(tmp_path / "cache"),
            "--output",
            str(tmp_path / "output"),
            *extra,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    result = tmp_path / "cache"
    result.mkdir()
    return result


def _result(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "output" / "result.json").read_text(encoding="utf-8"))


def _reports(tmp_path: Path) -> list[dict]:
    documents = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (tmp_path / "output").rglob("*.json")
    ]
    return [document for document in documents if "experiment" in document]


def test_offline_fix_retains_reports_hashes_checks_and_never_executes_subject(
    tmp_path: Path,
    cache: Path,
) -> None:
    sentinel = tmp_path / "executed"
    source = f"from pathlib import Path\nPath({str(sentinel)!r}).touch()\n\n" + ERROR
    case = _case(cache, before=source)
    case["runs"] += [
        _run("after", "errors", "/summary/findings", 0),
        {
            "id": "fix",
            "kind": "changes",
            "checks": [
                {"pointer": "/error_summary/removed", "equals": 1},
                {"pointer": "/error_summary/introduced", "equals": 0},
            ],
        },
    ]
    original = {path.name: path.read_bytes() for path in cache.iterdir()}
    run = _invoke(tmp_path, case)
    assert run.returncode == 0, run.stdout + run.stderr
    result = _result(tmp_path)
    assert result["state"] == "complete"
    assert len(result["jobs"]) == 3
    assert all(job["state"] == "passed" and job["checks"] for job in result["jobs"])
    provenance = result["provenance"]
    assert len(provenance["analyzer_fingerprint"]) == 64
    assert int(provenance["analyzer_fingerprint"], 16) >= 0
    assert set(provenance["source_hashes"].values()) == set(original)
    reports = _reports(tmp_path)
    assert len(reports) == 3
    assert {report["experiment"] for report in reports} == {
        "py-error-fallback-1",
        "change-review-1",
    }
    assert not sentinel.exists()
    assert original == {path.name: path.read_bytes() for path in cache.iterdir()}


def test_derived_candidate_and_recomputation_control(tmp_path: Path, cache: Path) -> None:
    case = _case(cache, before=DERIVED, after=DERIVED.replace("return count", "return len(items)"))
    case["runs"] = [
        _run("before", "derived", "/summary/findings", 1),
        _run("after", "derived", "/summary/findings", 0),
    ]
    run = _invoke(tmp_path, case)
    assert run.returncode == 0, run.stdout + run.stderr
    assert len(_reports(tmp_path)) == 2


def test_empty_baseline_can_report_genuine_introduction(tmp_path: Path, cache: Path) -> None:
    case = _case(cache, after=ERROR)
    case["snapshots"]["before"]["files"] = []
    case["runs"] = [
        {
            "id": "addition",
            "kind": "changes",
            "checks": [
                {"pointer": "/error_summary/introduced", "equals": 1},
            ],
        }
    ]
    run = _invoke(tmp_path, case)
    assert run.returncode == 0, run.stdout + run.stderr


@pytest.mark.parametrize(
    "pointer, expected",
    [
        ("/summary/findings", 19),
        ("/summary/not-present", 0),
        ("/summary/findings", True),
    ],
)
def test_failed_expectation_is_visible_mismatch_not_success(
    tmp_path: Path,
    cache: Path,
    pointer: str,
    expected: object,
) -> None:
    case = _case(cache)
    case["runs"] = [_run("before", "errors", pointer, expected)]
    run = _invoke(tmp_path, case)
    assert run.returncode == 1, run.stdout + run.stderr
    result = _result(tmp_path)
    assert result["state"] == "complete"
    assert result["jobs"][0]["state"] == "mismatch"
    assert result["jobs"][0]["checks"]
    assert len(_reports(tmp_path)) == 1


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_unavailable_or_corrupt_offline_blob_cannot_pass(
    tmp_path: Path,
    cache: Path,
    damage: str,
) -> None:
    case = _case(cache)
    digest = case["snapshots"]["before"]["files"][0]["sha256"]
    if damage == "missing":
        (cache / digest).unlink()
    else:
        (cache / digest).write_bytes(b"changed source")
    run = _invoke(tmp_path, case)
    assert run.returncode == 2, run.stdout + run.stderr
    result = _result(tmp_path)
    assert result["state"] == "incomplete"
    assert any(job["state"] == "error" for job in result["jobs"])


@pytest.mark.parametrize(
    "path", ["../escape.py", "/absolute.py", "C:/outside.py", "a\\..\\escape.py"]
)
def test_manifest_rejects_unsafe_source_paths(tmp_path: Path, cache: Path, path: str) -> None:
    case = _case(cache)
    case["snapshots"]["before"]["files"][0]["path"] = path
    run = _invoke(tmp_path, case)
    assert run.returncode == 2, run.stdout + run.stderr
    assert not (tmp_path / "escape.py").exists()


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf"])
def test_timeout_must_be_finite_and_positive(tmp_path: Path, cache: Path, timeout: str) -> None:
    run = _invoke(tmp_path, _case(cache), "--timeout", timeout)
    assert run.returncode == 2, run.stdout + run.stderr


def test_hard_worker_deadline_records_incomplete(tmp_path: Path, cache: Path) -> None:
    started = time.monotonic()
    run = _invoke(tmp_path, _case(cache), "--timeout", "0.000001")
    assert time.monotonic() - started < 10
    assert run.returncode == 2, run.stdout + run.stderr
    result = _result(tmp_path)
    assert result["state"] == "incomplete"
    assert any(job["state"] == "timeout" for job in result["jobs"])


def test_existing_output_is_rejected_without_overwriting(tmp_path: Path, cache: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    prior = output / "result.json"
    prior.write_bytes(b"previous evidence")
    run = _invoke(tmp_path, _case(cache))
    assert run.returncode == 2, run.stdout + run.stderr
    assert prior.read_bytes() == b"previous evidence"


@pytest.mark.parametrize(
    "invalid",
    [
        "schema-version",
        "unknown-root-field",
        "unknown-case-field",
        "duplicate-case",
        "duplicate-run",
        "empty-cases",
        "empty-checks",
        "unsafe-case-id",
        "unsafe-run-id",
    ],
)
def test_manifest_rejects_ambiguous_or_vacuous_evaluation(
    tmp_path: Path,
    cache: Path,
    invalid: str,
) -> None:
    case = _case(cache)
    manifest: dict = {"schema_version": 1, "cases": [case]}
    if invalid == "schema-version":
        manifest["schema_version"] = 2
    elif invalid == "unknown-root-field":
        manifest["casess"] = []
    elif invalid == "unknown-case-field":
        case["runss"] = []
    elif invalid == "duplicate-case":
        manifest["cases"].append(case)
    elif invalid == "duplicate-run":
        case["runs"].append(case["runs"][0].copy())
    elif invalid == "empty-cases":
        manifest["cases"] = []
    elif invalid == "empty-checks":
        case["runs"][0]["checks"] = []
    elif invalid == "unsafe-case-id":
        case["id"] = "../escaped"
    else:
        case["runs"][0]["id"] = "../escaped"
    run = _invoke(tmp_path, case, manifest_override=manifest)
    assert run.returncode == 2, run.stdout + run.stderr


def test_nested_json_comparison_does_not_equate_boolean_with_count(
    tmp_path: Path, cache: Path
) -> None:
    case = _case(cache)
    expected = {
        "unit": "exception-handlers",
        "files_analyzed": True,
        "files_failed": 0,
        "encountered": 1,
        "assessed": 1,
        "unresolved": 0,
        "findings": 1,
        "unresolved_reasons": [],
    }
    case["runs"] = [_run("before", "errors", "/summary", expected)]
    run = _invoke(tmp_path, case)
    assert run.returncode == 1, run.stdout + run.stderr
    assert _result(tmp_path)["jobs"][0]["state"] == "mismatch"


def test_mismatch_does_not_skip_other_jobs(tmp_path: Path, cache: Path) -> None:
    case = _case(cache)
    case["runs"] = [
        _run("before", "errors", "/summary/findings", 999),
        _run("after", "errors", "/summary/findings", 0),
    ]
    run = _invoke(tmp_path, case)
    assert run.returncode == 1, run.stdout + run.stderr
    assert [job["state"] for job in _result(tmp_path)["jobs"]] == ["mismatch", "passed"]
    assert len(_reports(tmp_path)) == 2


def test_parse_failure_is_incomplete_even_when_zero_findings_were_expected(
    tmp_path: Path,
    cache: Path,
) -> None:
    case = _case(cache, before="def invalid(:\n")
    case["runs"] = [_run("before", "errors", "/summary/findings", 0)]
    run = _invoke(tmp_path, case)
    assert run.returncode == 2, run.stdout + run.stderr
    result = _result(tmp_path)
    assert result["state"] == "incomplete"
    assert result["jobs"][0]["state"] == "error"
    assert _reports(tmp_path)[0]["diagnostics"]


def test_unresolved_subject_can_pass_explicit_coverage_gap_expectation(
    tmp_path: Path,
    cache: Path,
) -> None:
    case = _case(cache, before="class Example:\n    def method(self):\n        return 1\n")
    case["label"] = "coverage-gap"
    case["runs"] = [_run("before", "derived", "/summary/assessed", 0)]
    case["runs"][0]["checks"].append({"pointer": "/summary/unresolved", "equals": 1})
    run = _invoke(tmp_path, case)
    assert run.returncode == 0, run.stdout + run.stderr
    assert _result(tmp_path)["jobs"][0]["state"] == "passed"
