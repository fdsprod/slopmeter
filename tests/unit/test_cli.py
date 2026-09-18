"""Behavioral tests for the command-line entry point."""

from typer.testing import CliRunner

from slop_measure.cli import app


def test_help_identifies_the_project_and_its_purpose() -> None:
    """The root help output gives users the product name and purpose."""
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0, result.output
    assert "slop.measure" in result.output
    assert "Measure redundant and structurally eroded source code." in result.output
