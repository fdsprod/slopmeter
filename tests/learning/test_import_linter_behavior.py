"""Retained CLI observations for isolated architecture checks."""

import os
import subprocess
import sys
from pathlib import Path


def test_cli_checks_copied_packages_and_detects_indirect_forbidden_imports(tmp_path: Path) -> None:
    package = tmp_path / "learning_architecture"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "domain.py").write_text("import learning_architecture.bridge\n", encoding="utf-8")
    (package / "bridge.py").write_text("", encoding="utf-8")
    (package / "cli.py").write_text("", encoding="utf-8")
    config = tmp_path / "pyproject.toml"
    config.write_text(
        """[tool.importlinter]
root_package = "learning_architecture"
[[tool.importlinter.contracts]]
name = "Observed boundary"
type = "forbidden"
source_modules = ["learning_architecture.domain"]
forbidden_modules = ["learning_architecture.cli"]
""",
        encoding="utf-8",
    )
    command = [
        sys.executable,
        "-c",
        "from importlinter.cli import lint_imports_command; lint_imports_command()",
        "--config",
        str(config),
        "--no-cache",
        "--no-logo",
    ]
    environment = {**os.environ, "PYTHONPATH": str(tmp_path), "NO_COLOR": "1"}
    clean = subprocess.run(  # noqa: S603
        command, cwd=tmp_path, env=environment, capture_output=True, text=True, check=False
    )
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "Observed boundary KEPT" in clean.stdout

    (package / "bridge.py").write_text("import learning_architecture.cli\n", encoding="utf-8")
    broken = subprocess.run(  # noqa: S603
        command, cwd=tmp_path, env=environment, capture_output=True, text=True, check=False
    )
    # The CLI resolves the isolated package from PYTHONPATH, returns 1 for a
    # broken contract, and checks transitive imports without additional options.
    assert broken.returncode == 1, broken.stdout + broken.stderr
    assert "Observed boundary BROKEN" in broken.stdout
    assert "learning_architecture.bridge" in broken.stdout
