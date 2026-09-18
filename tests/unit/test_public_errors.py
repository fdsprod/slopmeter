"""Public failures have stable exit classes without leaking internal details."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest, scan
from slop_measure.cli import app
from slop_measure.errors import (
    AnalysisFailure,
    InputError,
    InvalidRuleSelection,
    InvalidSource,
    SelectionError,
    error_message,
    exit_code,
)


@pytest.mark.parametrize("kind", [InputError, InvalidRuleSelection, InvalidSource, SelectionError])
def test_input_errors_share_stable_exit_code_and_direct_message(kind: type[Exception]) -> None:
    error = kind("Review this input.")
    assert isinstance(error, InputError)
    assert exit_code(error) == 2
    assert error_message(error) == "Invalid analysis input: Review this input."


def test_analysis_and_unexpected_failures_have_exit_three_without_internal_details() -> None:
    failure = AnalysisFailure("Strict analysis failed: source could not be parsed.")
    assert exit_code(failure) == 3
    assert error_message(failure) == str(failure)
    internal = RuntimeError("private-token fixture detail")
    assert exit_code(internal) == 3
    assert error_message(internal) == "Analysis failed: RuntimeError"
    assert exit_code(ValueError("internal bug")) == 3


def test_missing_directory_is_invalid_source_in_public_api(tmp_path: Path) -> None:
    with pytest.raises(InvalidSource):
        scan(
            SnapshotRequest(
                target=DirectorySourceReference(root=tmp_path / "missing"), config=AnalysisConfig()
            )
        )


@pytest.mark.parametrize(
    "contents", ["invalid = [", "complexity_threshold = 0", 'enabled_rules = ["py.unknown-rule"]']
)
def test_invalid_configuration_is_exit_two_across_analysis_commands(
    tmp_path: Path,
    contents: str,
) -> None:
    (tmp_path / "slop.toml").write_text(contents, encoding="utf-8")
    for arguments in (
        ["score", str(tmp_path)],
        ["findings", "--root", str(tmp_path)],
        ["rules", "--root", str(tmp_path)],
    ):
        result = CliRunner().invoke(app, arguments)
        assert result.exit_code == 2, result.output
        assert "Invalid analysis input:" in result.output
        assert "Traceback" not in result.output


def test_unreadable_configuration_is_input_error(tmp_path: Path) -> None:
    (tmp_path / "slop.toml").mkdir()
    result = CliRunner().invoke(app, ["score", str(tmp_path)])
    assert result.exit_code == 2, result.output
    assert "Invalid analysis input:" in result.output


def test_cli_internal_failure_is_sanitized_and_strict_failure_keeps_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def crash(*args, **kwargs):
        raise RuntimeError("private-token fixture detail")

    monkeypatch.setattr("slop_measure.application.service.AnalysisService.scan", crash)
    result = CliRunner().invoke(app, ["score", str(tmp_path)])
    assert result.exit_code == 3
    assert "Analysis failed: RuntimeError" in result.output
    assert "private-token" not in result.output
