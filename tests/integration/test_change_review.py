"""Change review preserves evidence continuity without treating missing analysis as a fix."""

import hashlib
import json
from pathlib import Path

import pytest
from test_git_comparison import git
from typer.testing import CliRunner

from slop_measure import api
from slop_measure.api import AnalysisConfig, ComparisonRequest, DirectorySourceReference
from slop_measure.cli import app

ELSE_SOURCE = "def choose(flag):\n    if flag:\n        return 1\n    else:\n        return 2\n"
LITERAL_SOURCE = 'def label():\n    return f"hello"\n'


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    baseline, current = tmp_path / "baseline", tmp_path / "current"
    baseline.mkdir()
    current.mkdir()
    return baseline, current


def write(root: Path, path: str, source: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8", newline="\n")


def request(roots: tuple[Path, Path], **settings) -> ComparisonRequest:
    return ComparisonRequest(
        baseline=DirectorySourceReference(root=roots[0]),
        current=DirectorySourceReference(root=roots[1]),
        config=AnalysisConfig(**settings),
    )


def findings(report, rule: str) -> list[dict]:
    result = []
    for change in report.model_dump(mode="json")["patterns"]:
        occurrences = []
        for side in ("baseline", "current"):
            value = change.get(side, [])
            occurrences.extend(value if isinstance(value, list) else [value])
        if any(item["finding"]["rule_id"] == f"py.{rule}" for item in occurrences):
            result.append(change)
    return result


def test_line_shift_persists_finding_and_preserves_both_source_locations(roots) -> None:
    write(roots[0], "choose.py", ELSE_SOURCE)
    current = "# A new heading\n\n" + ELSE_SOURCE
    write(roots[1], "choose.py", current)

    report = api.review_change(request(roots))

    changes = findings(report, "redundant-else-after-return")
    assert len(changes) == 1
    change = changes[0]
    assert change["state"] == "persisted"
    assert change["baseline"]["finding"]["span"] == {"start_line": 4, "end_line": 4}
    assert change["current"]["finding"]["span"] == {"start_line": 6, "end_line": 6}
    assert change["baseline"]["source_sha256"] == hashlib.sha256(ELSE_SOURCE.encode()).hexdigest()
    assert change["current"]["source_sha256"] == hashlib.sha256(current.encode()).hexdigest()
    assert report.summary["introduced"] == report.summary["removed"] == 0


def test_exact_content_directory_rename_is_continuity(roots) -> None:
    write(roots[0], "old.py", LITERAL_SOURCE)
    write(roots[1], "package/new.py", LITERAL_SOURCE)

    changes = findings(api.review_change(request(roots)), "literal-fstring")

    assert len(changes) == 1 and changes[0]["state"] == "persisted"
    assert changes[0]["baseline"]["finding"]["path"] == "old.py"
    assert changes[0]["current"]["finding"]["path"] == "package/new.py"


@pytest.mark.parametrize("present_side,state", [(0, "removed"), (1, "introduced")])
def test_findings_in_added_or_deleted_files_have_one_owned_side(roots, present_side, state) -> None:
    write(roots[present_side], "label.py", LITERAL_SOURCE)

    changes = findings(api.review_change(request(roots)), "literal-fstring")

    assert len(changes) == 1 and changes[0]["state"] == state
    expected_side = "baseline" if present_side == 0 else "current"
    absent_side = "current" if present_side == 0 else "baseline"
    assert changes[0][expected_side]["finding"]["path"] == "label.py"
    assert absent_side not in changes[0]


def test_adding_another_occurrence_preserves_multiplicity(roots) -> None:
    write(roots[0], "label.py", LITERAL_SOURCE)
    write(roots[1], "label.py", LITERAL_SOURCE + '\ndef other():\n    return f"hello"\n')

    changes = findings(api.review_change(request(roots)), "literal-fstring")

    assert sorted(change["state"] for change in changes) == ["introduced", "persisted"]
    persisted = next(change for change in changes if change["state"] == "persisted")
    introduced = next(change for change in changes if change["state"] == "introduced")
    assert persisted["current"]["finding"]["span"]["start_line"] == 2
    assert introduced["current"]["finding"]["span"]["start_line"] == 5


def test_changed_literal_at_unique_callable_rule_site_is_changed(roots) -> None:
    write(roots[0], "label.py", LITERAL_SOURCE)
    write(roots[1], "label.py", LITERAL_SOURCE.replace("hello", "goodbye"))

    changes = findings(api.review_change(request(roots)), "literal-fstring")

    assert len(changes) == 1 and changes[0]["state"] == "changed"
    assert changes[0]["baseline"]["source_sha256"] != changes[0]["current"]["source_sha256"]


def test_repeated_changed_module_sites_are_unresolved_without_a_unique_match(roots) -> None:
    write(roots[0], "labels.py", 'first = f"alpha"\nsecond = f"beta"\n')
    write(roots[1], "labels.py", 'left = f"gamma"\nright = f"delta"\n')

    changes = findings(api.review_change(request(roots)), "literal-fstring")

    assert changes and all(change["state"] == "unresolved" for change in changes)
    assert sum(len(change["baseline"]) for change in changes) == 2
    assert sum(len(change["current"]) for change in changes) == 2
    assert all(change["reason"].strip() for change in changes)


def test_same_else_line_does_not_prove_continuity_after_surrounding_rewrite(roots) -> None:
    write(roots[0], "choose.py", ELSE_SOURCE)
    write(
        roots[1],
        "choose.py",
        "def unrelated(value):\n    if value > 10:\n        return 'large'\n"
        "    else:\n        return 'small'\n",
    )

    changes = findings(api.review_change(request(roots)), "redundant-else-after-return")

    assert changes and all(change["state"] in {"changed", "unresolved"} for change in changes)


@pytest.mark.parametrize("failed_side", [0, 1])
def test_parse_failure_never_turns_missing_evidence_into_introduced_or_removed(roots, failed_side):
    write(roots[1 - failed_side], "label.py", LITERAL_SOURCE)
    write(roots[failed_side], "label.py", "def broken(:\n")

    report = api.review_change(request(roots))

    changes = findings(report, "literal-fstring")
    assert len(changes) == 1 and changes[0]["state"] == "unresolved"
    known_side = "current" if failed_side == 0 else "baseline"
    missing_side = "baseline" if failed_side == 0 else "current"
    assert len(changes[0][known_side]) == 1 and changes[0][missing_side] == []
    assert changes[0]["reason"].strip()
    assert any(
        item.path is not None and item.path.root == "label.py" for item in report.limitations
    )
    assert report.summary["introduced"] == report.summary["removed"] == 0


def test_unsupported_and_failed_files_remain_visible_when_no_findings_exist(roots) -> None:
    for root in roots:
        write(root, "unknown.ts", "export const value = 1;\n")
        write(root, "broken.py", "def broken(:\n")

    report = api.review_change(request(roots))

    assert report.patterns == ()
    assert any(item.language == "typescript" for item in report.limitations)
    assert any(
        item.path is not None and item.path.root == "broken.py" for item in report.limitations
    )
    assert any(item.detail.state.value == "unsupported" for item in report.coverage)


def test_api_is_deterministic_unscored_read_only_and_does_not_execute_targets(roots, tmp_path):
    marker = tmp_path / "executed"
    source = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n" + LITERAL_SOURCE
    for root in roots:
        write(root, "label.py", source)
    selected = request(roots)
    before = api.compare(selected).model_dump_json()
    contents = {path: path.read_bytes() for root in roots for path in root.rglob("*.py")}

    report = api.review_change(selected)

    wire = report.model_dump(mode="json")
    assert wire["schema_version"] == "1" and wire["experiment"] == "change-review-1"
    assert not {"score", "cohorts", "slop_score"} & wire.keys()
    assert wire["analysis"]["baseline"]["root"] == str(roots[0].resolve())
    assert wire["analysis"]["current"]["root"] == str(roots[1].resolve())
    assert report.model_dump_json() == api.review_change(selected).model_dump_json()
    assert api.compare(selected).model_dump_json() == before
    assert contents == {path: path.read_bytes() for root in roots for path in root.rglob("*.py")}
    assert not marker.exists()


def test_cli_json_matches_api_and_plain_output_explains_unscored_evidence(roots) -> None:
    write(roots[1], "label.py", LITERAL_SOURCE)
    args = ["changes", str(roots[0]), str(roots[1]), "--lang", "py"]
    runner = CliRunner()

    result = runner.invoke(app, [*args, "--json"])

    assert result.exit_code == 0, result.output
    expected = api.review_change(request(roots, languages=("python",))).model_dump(mode="json")
    assert json.loads(result.stdout) == expected
    plain = runner.invoke(app, args)
    assert plain.exit_code == 0, plain.output
    text = " ".join(plain.stdout.lower().split())
    for term in ("introduced", "label.py", "literal-fstring", "unscored"):
        assert term in text


def test_cli_external_config_keeps_exclusions_and_test_cohort(roots, tmp_path) -> None:
    write(roots[1], "test_label.py", LITERAL_SOURCE)
    write(roots[1], "excluded.py", LITERAL_SOURCE)
    config = tmp_path / "selection.toml"
    config.write_text('exclusions=["excluded.py"]\nlanguages=[]\n', encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["changes", *map(str, roots), "--config", str(config), "--lang", "py", "--json"],
    )

    assert result.exit_code == 0, result.output
    wire = json.loads(result.stdout)
    assert wire["provenance"]["config"]["languages"] == ["python"]
    assert len(wire["patterns"]) == 1
    assert wire["patterns"][0]["current"]["cohort"] == "test"
    assert wire["patterns"][0]["current"]["finding"]["path"] == "test_label.py"


def test_git_cli_pins_rename_evidence_without_changing_dirty_checkout(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Lineage test")
    git(root, "config", "user.email", "lineage@example.invalid")
    write(root, "old.py", LITERAL_SOURCE)
    git(root, "add", ".")
    git(root, "commit", "-m", "baseline")
    baseline = git(root, "rev-parse", "HEAD").decode().strip()
    git(root, "mv", "old.py", "new.py")
    git(root, "commit", "-m", "rename")
    current = git(root, "rev-parse", "HEAD").decode().strip()
    write(root, "new.py", "dirty = True\n")
    write(root, "untracked.py", "untracked = True\n")
    index = (root / ".git/index").read_bytes()
    status = git(root, "status", "--porcelain=v1")
    contents = {path: path.read_bytes() for path in root.glob("*.py")}

    result = CliRunner().invoke(
        app, ["changes", "HEAD~1", "HEAD", "--repo", str(root), "--json"]
    )

    assert result.exit_code == 0, result.output
    wire = json.loads(result.stdout)
    assert wire["analysis"]["baseline"]["revision"] == baseline
    assert wire["analysis"]["current"]["revision"] == current
    assert len(wire["patterns"]) == 1 and wire["patterns"][0]["state"] == "persisted"
    assert wire["patterns"][0]["current"]["finding"]["path"] == "new.py"
    assert (root / ".git/index").read_bytes() == index
    assert git(root, "status", "--porcelain=v1") == status
    assert {path: path.read_bytes() for path in root.glob("*.py")} == contents
