"""Every report explains what its measurements support and how to review them."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.cli import app
from slop_measure.domain.reports import AnalysisReport
from slop_measure.domain.scoring import ScoreContribution
from slop_measure.reporting.terminal import render_explanation, render_snapshot


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    (tmp_path / "a.py").write_text(
        "def f(flag):\n    return True if flag else False\n", encoding="utf-8"
    )
    (tmp_path / "slop.toml").write_text('calibration_profile = "__raw__"\n', encoding="utf-8")
    return tmp_path


def arguments(command: str, project: Path) -> list[str]:
    if command == "compare":
        return [command, str(project), str(project)]
    if command == "explain":
        return [command, "a.py", "--root", str(project)]
    if command in {"findings", "rules"}:
        return [command, "--root", str(project)]
    return [command, str(project)]


def test_api_owns_immutable_interpretation_and_roundtrips_it(project: Path) -> None:
    report = scan(
        SnapshotRequest(
            target=DirectorySourceReference(root=project),
            config=AnalysisConfig(calibration_profile="__raw__"),
        )
    )
    guidance = getattr(report, "interpretation")  # noqa: B009 - contract precedes model implementation
    assert guidance.version == "1.0"
    for field in ("purpose", "score_meaning", "disposition_template"):
        assert isinstance(getattr(guidance, field), str) and getattr(guidance, field).strip()
    for field in ("metric_meanings", "limitations", "review_steps"):
        assert isinstance(getattr(guidance, field), tuple) and getattr(guidance, field)
    with pytest.raises(ValidationError):
        guidance.purpose = "changed"
    restored = AnalysisReport.model_validate_json(report.model_dump_json())
    assert getattr(restored, "interpretation") == guidance  # noqa: B009
    payload = report.model_dump(mode="json")["interpretation"]
    assert json.loads(report.model_dump_json())["interpretation"] == payload


def test_interpretation_covers_score_limits_metrics_and_evidence_based_review(
    project: Path,
) -> None:
    result = CliRunner().invoke(app, ["score", str(project), "--json"])
    assert result.exit_code == 0, result.output
    guidance = json.loads(result.stdout)["interpretation"]
    text = json.dumps(guidance).lower()
    for term in (
        "lower",
        "calibrat",
        "probability",
        "raw",
        "ratio",
        "complexity",
        "threshold",
        "size",
        "zero",
        "correct",
        "high",
        "inspect",
        "refactor",
        "guard",
        "predicate",
        "short",
        "algorithm",
        "unavailable",
        "partial",
        "excluded",
        "compatible",
        "version",
        "profile",
        "config",
    ):
        assert term in text, term
    assert "percent" in text or "percentage" in text
    assert "sqrt" in text or "square root" in text
    assert "excess" in text or "above" in text
    disposition = guidance["disposition_template"].lower()
    for term in ("actionable", "defer", "no-change", "location", "evidence", "reason", "next"):
        assert term in disposition, term
    assert "overstat" in text and "understat" in text
    assert "provenance" in text and "gradual" in text and "binary" in text
    assert "v1" in text or "version 1" in text
    assert "v2" in text or "version 2" in text


@pytest.mark.parametrize(
    "command", ["score", "scan", "tree", "compare", "explain", "findings", "rules"]
)
def test_every_successful_command_has_pure_json_guidance_and_compact_expanded_text(
    project: Path, command: str
) -> None:
    runner = CliRunner()
    invocation = arguments(command, project)
    reference = runner.invoke(app, ["score", str(project), "--json"])
    assert reference.exit_code == 0, reference.output
    expected = json.loads(reference.stdout)["interpretation"]
    machine = runner.invoke(app, [*invocation, "--json"])
    assert machine.exit_code == 0, machine.output
    assert json.loads(machine.stdout)["interpretation"] == expected
    compact = runner.invoke(app, [*invocation, "--ascii", "--no-color"])
    expanded = runner.invoke(app, [*invocation, "--ascii", "--no-color", "--verbose"])
    assert compact.exit_code == expanded.exit_code == 0, (compact.output, expanded.output)
    assert "How to read this report" in compact.stdout
    assert "How to read this report" in expanded.stdout
    compact_guide = compact.stdout.split("How to read this report", 1)[1]
    expanded_guide = expanded.stdout.split("How to read this report", 1)[1]
    assert len(expanded_guide) > len(compact_guide)
    assert "\x1b[" not in compact.stdout + expanded.stdout
    assert "lower" in compact_guide.lower() and "review" in compact_guide.lower()


def test_cli_automatically_uses_ascii_when_stdout_encoding_cannot_encode_glyphs(
    project: Path,
) -> None:
    environment = dict(os.environ, PYTHONIOENCODING="cp1252")
    result = subprocess.run(  # noqa: S603 - fixed CLI entry point and test-owned source directory
        [
            sys.executable,
            "-c",
            "from slop_measure.cli import app; app()",
            "score",
            str(project),
            "--no-color",
        ],
        env=environment,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("cp1252", errors="replace")
    output = result.stdout.decode("cp1252")
    assert "How to read this report" in output
    assert "UnicodeEncodeError" not in output


def test_contribution_transform_is_explicit_only_for_severity_weighted_scores() -> None:
    base = {
        "metric_id": "m4.erosion",
        "raw_value": 0.3,
        "percentile": 75,
        "weight": 0.4,
        "points": 30,
    }
    legacy = ScoreContribution.model_validate(base)
    assert getattr(legacy, "transform").value == "percentile"  # noqa: B009
    assert "transform" not in legacy.model_dump()
    assert "transform" not in legacy.model_dump(mode="json")
    weighted = ScoreContribution.model_validate(
        {**base, "points": 9, "transform": "severity-weighted"}
    )
    assert weighted.model_dump(mode="json")["transform"] == "severity-weighted"
    assert ScoreContribution.model_validate_json(weighted.model_dump_json()) == weighted
    with pytest.raises(ValidationError):
        ScoreContribution.model_validate({**base, "transform": "unknown"})


def test_explanation_labels_transformed_contribution_without_relabeling_legacy() -> None:
    fixture = Path(__file__).parents[1] / "golden" / "scoring.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    original = AnalysisReport.model_validate(payload)
    legacy = render_explanation(original, "a.py", width=140, ascii=True, color=False)
    assert "severity-weighted" not in legacy.split("How to read this report", 1)[0]
    file = next(
        item
        for item in payload["cohorts"][0]["current"]["files"]
        if item["evidence"]["path"] == "a.py"
    )
    contribution = next(
        item for item in file["score"]["contributions"] if item["metric_id"] == "m4.erosion"
    )
    contribution.update(transform="severity-weighted", points=9)
    file["score"].update(points=54, band="moderate")
    rendered = render_explanation(
        AnalysisReport.model_validate(payload), "a.py", width=140, ascii=True, color=False
    )
    measurement = rendered.split("How to read this report", 1)[0]
    transformed = [line for line in measurement.splitlines() if "severity-weighted" in line]
    assert len(transformed) == 1
    assert "m4.erosion" in transformed[0] and "9.0" in transformed[0]


def test_full_guide_explains_severity_weighted_contributions(project: Path) -> None:
    runner = CliRunner()
    machine = runner.invoke(app, ["score", str(project), "--json"])
    assert machine.exit_code == 0, machine.output
    definitions = " ".join(json.loads(machine.stdout)["interpretation"]["metric_meanings"]).lower()
    assert "severity-weighted" in definitions
    assert "percentile * raw value * weight" in definitions
    assert "individual" in definitions and "contribution" in definitions
    expanded = runner.invoke(app, ["score", str(project), "--verbose", "--ascii", "--no-color"])
    assert expanded.exit_code == 0, expanded.output
    guide = expanded.stdout.split("How to read this report", 1)[1].lower()
    assert "severity-weighted" in guide
    assert "percentile * raw value * weight" in " ".join(guide.split())


def test_verbose_raw_metric_names_its_reference_percentile() -> None:
    fixture = Path(__file__).parents[1] / "golden" / "scoring.json"
    report = AnalysisReport.model_validate_json(fixture.read_text(encoding="utf-8"))
    output = render_snapshot(report, width=160, ascii=True, color=False, verbose=True)
    raw_rows = [
        line
        for line in output.split("How to read this report", 1)[0].splitlines()
        if "[" in line and ("Combined verbosity" in line or "Erosion  " in line)
    ]
    assert len(raw_rows) == 2
    assert all("percentile 33.3" in line.lower() for line in raw_rows)
    assert all("metric 33.3/100" not in line for line in raw_rows)
