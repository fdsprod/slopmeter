"""Hand-counted raw scan fixture through the public API, CLI, and serializers."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure import __version__
from slop_measure.api import compare, scan
from slop_measure.cli import app
from slop_measure.config import AnalysisConfig
from slop_measure.domain.requests import ComparisonRequest, SnapshotRequest
from slop_measure.domain.source import DirectorySourceReference, GitSourceReference
from slop_measure.errors import AnalysisFailure
from slop_measure.reporting.json import serialize_report
from slop_measure.reporting.terminal import render_snapshot

FIXTURE = Path(__file__).parents[1] / "fixtures" / "basic"
METRIC_IDS = ["m1.loc-delta", "m2.pattern-verbosity", "m3.clone-verbosity", "m4.erosion"]


@pytest.fixture
def basic_project(tmp_path: Path) -> Path:
    for source in FIXTURE.rglob("*.source"):
        destination = tmp_path / source.relative_to(FIXTURE).with_suffix("")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    return tmp_path


def request(root: Path, *, strict: bool = False) -> SnapshotRequest:
    return SnapshotRequest(
        target=DirectorySourceReference(root=root), config=AnalysisConfig(strict=strict)
    )


def test_basic_scan_matches_hand_counted_manifest_and_never_executes_source(
    basic_project: Path,
) -> None:
    report = scan(request(basic_project))
    payload = report.model_dump(mode="json")
    actual = {
        "files": [
            [
                cohort["cohort"],
                item["evidence"]["path"],
                item["evidence"]["sloc"],
                item["evidence"]["sloc_lines"],
                item["evidence"]["parse_state"],
            ]
            for cohort in payload["cohorts"]
            for item in cohort["current"]["files"]
        ],
        "coverage": sorted(
            [
                [
                    item["detail"]["state"],
                    item["detail"]["cohort"],
                    item["detail"]["language"],
                    item["detail"]["file_count"],
                    item["detail"]["sloc"],
                    item["detail"]["reason"],
                ]
                for item in payload["coverage"]
            ]
        ),
        "cohort_metric_reasons": {
            cohort["cohort"]: [item["reason"] for item in cohort["current"]["metrics"]]
            for cohort in payload["cohorts"]
        },
        "score_reasons": {
            cohort["cohort"]: cohort["current"]["score"]["reason"] for cohort in payload["cohorts"]
        },
        "diagnostics": [
            [
                item["id"],
                item["source"],
                item["detail"]["code"],
                item["detail"]["path"],
                item["detail"]["severity"],
            ]
            for item in payload["diagnostics"]
        ],
    }
    assert actual == json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8"))
    assert not (basic_project / "EXECUTED").exists()
    assert payload["analysis"]["current"]["root"] == str(basic_project.resolve())
    assert report.provenance.tool_version == __version__
    assert report.provenance.config == AnalysisConfig()
    assert [(item.language, item.adapter_version) for item in report.provenance.analyzers] == [
        ("python", "python-files-1")
    ]
    for cohort in payload["cohorts"]:
        assert [item["metric_id"] for item in cohort["current"]["metrics"]] == METRIC_IDS
    bad = payload["cohorts"][0]["current"]["files"][1]
    assert all(item["diagnostic_id"] == "diagnostic-0001" for item in bad["metrics"][1:])


def test_json_is_stable_sorted_indented_and_cli_equivalent(basic_project: Path) -> None:
    report = scan(request(basic_project))
    serialized = serialize_report(report)
    assert serialized == json.dumps(report.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    assert serialize_report(scan(request(basic_project))) == serialized
    result = CliRunner().invoke(app, ["scan", str(basic_project), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == json.loads(serialized)


def test_strict_parse_failure_raises_and_cli_returns_three(basic_project: Path) -> None:
    with pytest.raises(AnalysisFailure):
        scan(request(basic_project, strict=True))
    result = CliRunner().invoke(app, ["scan", str(basic_project), "--strict", "--json"])
    assert result.exit_code == 3, result.output


@pytest.mark.parametrize(
    "arguments", [["--scope", "unknown"], ["--scope", "production", "--scope", "invalid"]]
)
def test_cli_rejects_unknown_scopes(basic_project: Path, arguments: list[str]) -> None:
    assert CliRunner().invoke(app, ["scan", str(basic_project), *arguments]).exit_code == 2


def test_cli_missing_root_and_invalid_config_return_two(tmp_path: Path) -> None:
    assert CliRunner().invoke(app, ["scan", str(tmp_path / "missing")]).exit_code == 2
    (tmp_path / "slop.toml").write_text("[broken", encoding="utf-8")
    assert CliRunner().invoke(app, ["scan", str(tmp_path)]).exit_code == 2


def test_scope_changes_terminal_selection_but_json_keeps_all_cohorts(basic_project: Path) -> None:
    result = CliRunner().invoke(app, ["scan", str(basic_project), "--scope", "test", "--json"])
    assert result.exit_code == 0, result.output
    assert {cohort["cohort"] for cohort in json.loads(result.stdout)["cohorts"]} == {
        "production",
        "test",
    }
    report = scan(request(basic_project))
    for width in (40, 80):
        rendered = render_snapshot(report, scope="test", width=width, color=False)
        assert "higher is worse" in rendered.lower()
        assert "unavailable" in rendered.lower()
        assert "production" in rendered.lower() and "test" in rendered.lower()
        assert "\x1b[" not in rendered
    plain = CliRunner().invoke(app, ["scan", str(basic_project), "--no-color"])
    assert plain.exit_code == 0 and "\x1b[" not in plain.stdout


def test_empty_scan_retains_both_python_cohorts(tmp_path: Path) -> None:
    payload = scan(request(tmp_path)).model_dump(mode="json")
    assert [(item["language"], item["cohort"]) for item in payload["cohorts"]] == [
        ("python", "production"),
        ("python", "test"),
    ]
    for cohort in payload["cohorts"]:
        assert cohort["current"]["files"] == []
        assert cohort["current"]["score"]["reason"] == "no-source-lines"
        assert [item["reason"] for item in cohort["current"]["metrics"]] == [
            "no-baseline",
            "no-source-lines",
            "no-source-lines",
            "no-source-lines",
        ]


def test_git_scan_and_comparison_are_explicitly_unavailable(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Git revision"):
        scan(
            SnapshotRequest(
                target=GitSourceReference(root=tmp_path, revision="HEAD"), config=AnalysisConfig()
            )
        )
    reference = DirectorySourceReference(root=tmp_path)
    with pytest.raises(NotImplementedError):
        compare(ComparisonRequest(baseline=reference, current=reference, config=AnalysisConfig()))
