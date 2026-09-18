"""Hand-counted raw scan fixture through the public API, CLI, and serializers."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure import __version__
from slop_measure.api import compare, scan
from slop_measure.cli import app
from slop_measure.config import AnalysisConfig, load_analysis_config
from slop_measure.domain.reports import SnapshotAnalysis
from slop_measure.domain.requests import ComparisonRequest, SnapshotRequest
from slop_measure.domain.source import (
    DirectorySourceIdentity,
    DirectorySourceReference,
    GitSourceReference,
)
from slop_measure.errors import AnalysisFailure, InvalidSource
from slop_measure.reporting.json import serialize_report
from slop_measure.reporting.terminal import render_snapshot

FIXTURE = Path(__file__).parents[1] / "fixtures" / "basic"
METRIC_IDS = [
    "m1.loc-delta",
    "m2.pattern-verbosity",
    "m3.clone-verbosity",
    "m4.erosion",
    "verbosity.combined",
]


@pytest.fixture(autouse=True)
def isolate_parent_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


@pytest.fixture
def basic_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for source in FIXTURE.rglob("*"):
        if not source.is_file() or source.name == "expected.json":
            continue
        destination = tmp_path / source.relative_to(FIXTURE)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    monkeypatch.setattr(
        "slop_measure.cli.load_analysis_config",
        lambda root, **kwargs: load_analysis_config(root, **kwargs).model_copy(
            update={"calibration_profile": "__raw__"}
        ),
    )
    return tmp_path


def request(root: Path, *, strict: bool = False) -> SnapshotRequest:
    return SnapshotRequest(
        target=DirectorySourceReference(root=root),
        config=AnalysisConfig(calibration_profile="__raw__", strict=strict),
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
        "excluded_directories": [
            [item["source"], item["detail"]["path"], item["detail"]["reason"]]
            for item in payload["excluded_directories"]
        ],
        "cohort_metric_results": {
            cohort["cohort"]: [
                item["reason"]
                if item["state"] == "unavailable"
                else {"value": item["raw"]["value"]}
                for item in cohort["current"]["metrics"]
            ]
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
    assert report.provenance.config == AnalysisConfig(calibration_profile="__raw__")
    assert [(item.language, item.adapter_version) for item in report.provenance.analyzers] == [
        ("python", "python-clones-1")
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


def test_cli_defaults_to_current_directory_and_loads_root_config(
    basic_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (basic_project / "slop.toml").write_text(
        'complexity_threshold = 12\ncalibration_profile = "__raw__"\n', encoding="utf-8"
    )
    monkeypatch.chdir(basic_project)
    result = CliRunner().invoke(app, ["scan", "--json"])
    assert result.exit_code == 0, result.output
    expected = scan(
        SnapshotRequest(
            target=DirectorySourceReference(root=basic_project),
            config=load_analysis_config(basic_project),
        )
    )
    assert json.loads(result.stdout) == expected.model_dump(mode="json")
    assert json.loads(result.stdout)["provenance"]["config"]["complexity_threshold"] == 12


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


def test_cli_internal_scan_value_error_is_failure_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_scan(request: SnapshotRequest):
        raise ValueError("internal report invariant failed")

    monkeypatch.setattr("slop_measure.cli.scan", fail_scan)
    result = CliRunner().invoke(app, ["scan", str(tmp_path), "--json"])
    assert result.exit_code == 3, result.output


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
            "no-functions",
            "no-source-lines",
        ]


def test_git_scan_rejects_nonrepository_and_directory_comparison_works(tmp_path: Path) -> None:
    with pytest.raises(InvalidSource, match="repository"):
        scan(
            SnapshotRequest(
                target=GitSourceReference(root=tmp_path, revision="HEAD"),
                config=AnalysisConfig(calibration_profile="__raw__"),
            )
        )
    reference = DirectorySourceReference(root=tmp_path)
    report = compare(
        ComparisonRequest(
            baseline=reference,
            current=reference,
            config=AnalysisConfig(calibration_profile="__raw__"),
        )
    )
    assert report.analysis.kind == "comparison"


def test_public_api_exports_a_complete_directory_scan_interface(tmp_path: Path) -> None:
    from slop_measure.api import (  # noqa: PLC0415 - exercise the documented public import
        AnalysisConfig as PublicConfig,
        DirectorySourceReference as PublicDirectory,
        GitSourceReference as PublicGit,
        SnapshotRequest as PublicRequest,
        scan as public_scan,
    )

    public_request = PublicRequest(target=PublicDirectory(root=tmp_path), config=PublicConfig())
    assert public_scan(public_request).analysis.kind == "snapshot"
    assert PublicGit(root=tmp_path, revision="HEAD").revision == "HEAD"


def test_plain_terminal_snapshot_matches_approved_golden(basic_project: Path) -> None:
    report = scan(request(basic_project))
    normalized = report.model_copy(
        update={"analysis": SnapshotAnalysis(current=DirectorySourceIdentity(root=Path("PROJECT")))}
    )
    rendered = render_snapshot(normalized, width=80, color=False, ascii=True)
    expected = (Path(__file__).parent / "scan_basic.txt").read_text(encoding="utf-8")

    assert rendered == expected
