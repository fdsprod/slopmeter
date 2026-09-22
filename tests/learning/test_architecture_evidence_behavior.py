"""Retained observations for Grimp 3.17 and Import Linter 2.15.

These probes run outside the production suite. Marker writes are intentional:
they establish whether package discovery or contract loading executes target code.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _run(
    root: Path, script: str, *, source_root: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", script],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(source_root or root), "NO_COLOR": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_grimp_reads_src_layout_relative_imports_without_executing_package(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    _write(source_root, "observed/__init__.py", "raise RuntimeError('must not execute')\n")
    _write(source_root, "observed/service.py", "# heading\nfrom . import storage\n")
    _write(source_root, "observed/storage.py", "raise RuntimeError('must not execute')\n")
    result = _run(
        tmp_path,
        "import grimp, json; g = grimp.build_graph('observed', cache_dir=None); "
        "print(json.dumps({'edges': sorted(g.find_modules_directly_imported_by("
        "'observed.service')), 'details': g.get_import_details("
        "importer='observed.service', imported='observed.storage')}))",
        source_root=source_root,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    observed = json.loads(result.stdout)
    assert observed["edges"] == ["observed.storage"]
    assert observed["details"][0]["line_number"] == 2
    assert observed["details"][0]["line_contents"] == "from . import storage"
    # Details identify modules and source lines, but contain no filesystem path.
    assert "path" not in observed["details"][0]


def test_grimp_discovers_namespace_portion_without_executing_its_init(tmp_path: Path) -> None:
    _write(tmp_path, "observed_namespace/portion/__init__.py", "raise RuntimeError('no')\n")
    _write(tmp_path, "observed_namespace/portion/service.py", "from . import storage\n")
    _write(tmp_path, "observed_namespace/portion/storage.py", "")
    result = _run(
        tmp_path,
        "import grimp, json; g = grimp.build_graph('observed_namespace.portion', "
        "cache_dir=None); print(json.dumps(sorted(g.modules)))",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == [
        "observed_namespace.portion",
        "observed_namespace.portion.service",
        "observed_namespace.portion.storage",
    ]


def test_grimp_executes_regular_parent_before_rejecting_dotted_root(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "observed_parent/__init__.py",
        "from pathlib import Path\nPath('parent-executed').write_text('yes')\n",
    )
    _write(tmp_path, "observed_parent/child/__init__.py", "")
    result = _run(
        tmp_path,
        "import grimp; grimp.build_graph('observed_parent.child', cache_dir=None)",
    )
    # Rejection is too late to enforce the analyzer's no-target-execution invariant.
    assert result.returncode != 0
    assert "NotATopLevelModule" in result.stderr
    assert (tmp_path / "parent-executed").read_text() == "yes"


def test_grimp_static_graph_omits_dynamic_imports(tmp_path: Path) -> None:
    _write(tmp_path, "observed_dynamic/__init__.py", "")
    _write(tmp_path, "observed_dynamic/storage.py", "")
    _write(
        tmp_path,
        "observed_dynamic/service.py",
        "import importlib\nimportlib.import_module('observed_dynamic.storage')\n",
    )
    result = _run(
        tmp_path,
        "import grimp, json; g = grimp.build_graph('observed_dynamic', cache_dir=None); "
        "print(json.dumps(sorted(g.find_modules_directly_imported_by("
        "'observed_dynamic.service'))))",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == []


@pytest.mark.parametrize(
    ("contract", "breaking_import"),
    [
        (
            'type = "forbidden"\nsource_modules = ["observed_contract.service"]\n'
            'forbidden_modules = ["observed_contract.storage"]\n',
            "from . import storage\n",
        ),
        (
            'type = "layers"\n'
            'layers = ["observed_contract.storage", "observed_contract.service"]\n',
            "from . import storage\n",
        ),
    ],
    ids=["forbidden", "layers"],
)
def test_cli_applies_declared_contracts_with_source_lines(
    tmp_path: Path, contract: str, breaking_import: str
) -> None:
    _write(tmp_path, "observed_contract/__init__.py", "raise RuntimeError('no execution')\n")
    _write(tmp_path, "observed_contract/service.py", "")
    _write(tmp_path, "observed_contract/storage.py", "")
    _write(
        tmp_path,
        "pyproject.toml",
        '[tool.importlinter]\nroot_package = "observed_contract"\n'
        '[[tool.importlinter.contracts]]\nname = "Observed contract"\n' + contract,
    )
    script = (
        "import sys; from importlinter.cli import lint_imports; "
        "sys.exit(lint_imports(config_filename='pyproject.toml', "
        "no_cache=True, no_logo=True))"
    )
    clean = _run(tmp_path, script)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "Observed contract KEPT" in clean.stdout
    _write(tmp_path, "observed_contract/service.py", "# heading\n" + breaking_import)
    broken = _run(tmp_path, script)
    assert broken.returncode == 1, broken.stdout + broken.stderr
    assert "Observed contract BROKEN" in broken.stdout
    assert "observed_contract.service" in broken.stdout
    assert "observed_contract.storage (l.2)" in broken.stdout


def test_documented_api_reads_contracts_and_normalizes_root(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pyproject.toml",
        '[tool.importlinter]\nroot_package = "does_not_need_to_exist"\n'
        '[[tool.importlinter.contracts]]\nname = "Observed"\ntype = "forbidden"\n'
        'source_modules = ["a"]\nforbidden_modules = ["b"]\n',
    )
    result = _run(
        tmp_path,
        "import json; from importlinter import api; "
        "print(json.dumps(api.read_configuration('pyproject.toml')))",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    observed = json.loads(result.stdout)
    assert observed["session_options"]["root_packages"] == ["does_not_need_to_exist"]
    assert observed["contracts_options"][0]["forbidden_modules"] == ["b"]


def test_internal_report_access_requires_contract_registration(tmp_path: Path) -> None:
    _write(tmp_path, "observed_report/__init__.py", "")
    _write(tmp_path, "observed_report/service.py", "from . import storage\n")
    _write(tmp_path, "observed_report/storage.py", "")
    _write(
        tmp_path,
        "pyproject.toml",
        '[tool.importlinter]\nroot_package = "observed_report"\n'
        '[[tool.importlinter.contracts]]\nname = "Observed"\ntype = "forbidden"\n'
        'source_modules = ["observed_report.service"]\n'
        'forbidden_modules = ["observed_report.storage"]\n',
    )
    result = _run(
        tmp_path,
        "import json; from importlinter import configuration; "
        "from importlinter.application import use_cases; configuration.configure(); "
        "options = use_cases.read_user_options('pyproject.toml'); "
        "use_cases._register_contract_types(options); "
        "report = use_cases.create_report(options, cache_dir=None); "
        "print(json.dumps({'broken': report.broken_count, 'checks': "
        "[{'kept': check.kept, 'metadata_keys': sorted(check.metadata)} "
        "for contract, check in report.get_contracts_and_checks()]}))",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # Structured output exists, but requires undocumented application APIs and
    # private registration. The stable documented API only reads configuration.
    assert json.loads(result.stdout) == {
        "broken": 1,
        "checks": [{"kept": False, "metadata_keys": ["invalid_chains"]}],
    }


def test_custom_contract_configuration_can_execute_target_module(tmp_path: Path) -> None:
    _write(tmp_path, "observed_custom/__init__.py", "")
    _write(
        tmp_path,
        "observed_plugin.py",
        "from pathlib import Path\nPath('plugin-executed').write_text('yes')\n"
        "raise RuntimeError('plugin loaded')\n",
    )
    _write(
        tmp_path,
        "pyproject.toml",
        '[tool.importlinter]\nroot_package = "observed_custom"\n'
        'contract_types = ["custom: observed_plugin.Contract"]\n',
    )
    result = _run(
        tmp_path,
        "import sys; from importlinter.cli import lint_imports; "
        "sys.exit(lint_imports(config_filename='pyproject.toml', no_cache=True, no_logo=True))",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    # CLI catches the exception, but execution has already occurred.
    assert "plugin loaded" in result.stdout
    assert (tmp_path / "plugin-executed").read_text() == "yes"
