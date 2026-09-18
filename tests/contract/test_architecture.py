"""Architecture contracts exercised against isolated copies of the real package."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_FORBIDDEN = {
    "domain": ("application", "languages", "sources", "reporting", "api", "cli", "scoring"),
    "scoring": ("application", "languages", "sources", "reporting", "api", "cli"),
    "metrics": ("languages", "sources", "reporting", "cli"),
    "languages": ("application", "reporting", "api", "cli"),
    "reporting": ("languages", "sources"),
}


@pytest.fixture
def isolated_package(tmp_path: Path) -> Path:
    """Copy source and config without modifying the repository or its caches."""
    shutil.copytree(
        _ROOT / "src" / "slop_measure",
        tmp_path / "slop_measure",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copyfile(_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    return tmp_path


def run_contracts(root: Path) -> subprocess.CompletedProcess[str]:
    """Use the installed CLI and force import discovery to the isolated copy."""
    return subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-c",
            "from importlinter.cli import lint_imports_command; lint_imports_command()",
            "--config",
            str(root / "pyproject.toml"),
            "--no-cache",
            "--no-logo",
        ],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root), "NO_COLOR": "1"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_current_package_keeps_all_five_architecture_contracts(isolated_package: Path) -> None:
    result = run_contracts(isolated_package)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "5 kept, 0 broken" in output


@pytest.mark.parametrize(
    ("source", "forbidden"),
    [(source, target) for source, targets in _FORBIDDEN.items() for target in targets],
)
def test_forbidden_dependency_breaks_the_architecture_gate(
    isolated_package: Path, source: str, forbidden: str
) -> None:
    injected = isolated_package / "slop_measure" / source / "_architecture_violation.py"
    injected.write_text(f"import slop_measure.{forbidden}\n", encoding="utf-8")

    result = run_contracts(isolated_package)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "BROKEN" in output
    assert f"slop_measure.{source}._architecture_violation" in output
    assert f"slop_measure.{forbidden}" in output
