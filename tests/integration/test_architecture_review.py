"""Declared module boundaries use source evidence without importing target packages."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure import api
from slop_measure.api import AnalysisConfig, DirectorySourceReference, SnapshotRequest
from slop_measure.cli import app


@pytest.fixture(autouse=True)
def isolate_source_inventory(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


def project(tmp_path: Path, files: dict[str, str]) -> SnapshotRequest:
    for name, source in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return SnapshotRequest(
        target=DirectorySourceReference(root=tmp_path),
        config=AnalysisConfig(languages=frozenset({"python"})),
    )


def policy(**overrides):
    from slop_measure.domain.architecture import ArchitecturePolicy  # noqa: PLC0415

    return ArchitecturePolicy.model_validate(
        {
            "source_roots": ["src"],
            "forbidden": [{"source": "sample.controller", "target": "sample.storage"}],
            **overrides,
        }
    )


def test_forbidden_relative_import_has_owned_source_location_and_never_executes(tmp_path):
    marker = tmp_path / "executed"
    selected = project(
        tmp_path,
        {
            "src/sample/__init__.py": f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
            "src/sample/controller.py": "from . import storage\n",
            "src/sample/storage.py": "value = 1\n",
        },
    )

    report = api.inspect_architecture(selected, policy())

    assert not marker.exists()
    assert len(report.violations) == 1
    violation = report.violations[0]
    assert violation.edge.importer == "sample.controller"
    assert violation.edge.imported == "sample.storage"
    assert violation.edge.path.root == "src/sample/controller.py"
    assert violation.edge.span.start_line == 1
    assert report.fan_out["sample.controller"] == 1
    assert report.cycles == ()
    assert (
        report.model_dump_json() == api.inspect_architecture(selected, policy()).model_dump_json()
    )


def test_allowed_imports_and_direct_policy_do_not_infer_transitive_violations(tmp_path):
    selected = project(
        tmp_path,
        {
            "src/sample/__init__.py": "",
            "src/sample/controller.py": "from sample import service\n",
            "src/sample/service.py": "import sample.storage\n",
            "src/sample/storage.py": "",
        },
    )

    report = api.inspect_architecture(selected, policy())

    assert report.violations == ()
    assert ("sample.service", "sample.storage") in {(e.importer, e.imported) for e in report.edges}


def test_cycles_are_components_and_fanout_counts_unique_internal_targets(tmp_path):
    selected = project(
        tmp_path,
        {
            "src/sample/__init__.py": "",
            "src/sample/a.py": "import sample.b\nimport sample.b\n",
            "src/sample/b.py": "import sample.a\n",
            "src/sample/c.py": "import sample.a\n",
        },
    )

    report = api.inspect_architecture(selected, policy(forbidden=[]))

    assert report.cycles == (("sample.a", "sample.b"),)
    assert report.fan_out["sample.a"] == 1
    assert report.fan_out["sample.c"] == 1


def test_dynamic_and_missing_internal_imports_are_unresolved_and_parse_errors_survive(tmp_path):
    selected = project(
        tmp_path,
        {
            "src/sample/__init__.py": "",
            "src/sample/controller.py": 'import sample.missing\n__import__("sample.storage")\n',
            "src/sample/storage.py": "def broken(:\n",
        },
    )

    report = api.inspect_architecture(selected, policy())

    assert len(report.unresolved) >= 2
    assert all(item.reason for item in report.unresolved)
    assert any(item.path.root == "src/sample/storage.py" for item in report.diagnostics)


@pytest.mark.parametrize("source_root", ["../outside", "/absolute", "C:/outside"])
def test_policy_rejects_roots_outside_the_selected_repository(source_root):
    with pytest.raises(ValueError):
        policy(source_roots=[source_root])


def test_cli_loads_explicit_policy_and_emits_the_same_owned_report(tmp_path):
    selected = project(
        tmp_path,
        {
            "src/sample/__init__.py": "",
            "src/sample/controller.py": "import sample.storage\n",
            "src/sample/storage.py": "",
        },
    )
    config = tmp_path / "architecture.toml"
    config.write_text(
        'source_roots=["src"]\n[[forbidden]]\nsource="sample.controller"\ntarget="sample.storage"\n',
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "architecture",
            "--root",
            str(tmp_path),
            "--policy",
            str(config),
            "--lang",
            "py",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == api.inspect_architecture(selected, policy()).model_dump(
        mode="json"
    )


def test_package_attribute_prevents_proof_of_child_module_import(tmp_path):
    selected = project(
        tmp_path,
        {
            "src/sample/__init__.py": "storage = object()\n",
            "src/sample/controller.py": "from sample import storage\n",
            "src/sample/storage.py": "value = 1\n",
        },
    )
    report = api.inspect_architecture(selected, policy())
    assert not any(
        edge.importer == "sample.controller" and edge.imported == "sample.storage"
        for edge in report.edges
    )
    assert any(item.path.root == "src/sample/controller.py" for item in report.unresolved)


def test_architecture_report_roundtrips_and_rejects_false_projections(tmp_path):
    selected = project(tmp_path, {"src/sample/__init__.py": ""})
    report = api.inspect_architecture(selected, policy())
    assert type(report).model_validate_json(report.model_dump_json()) == report
    wire = report.model_dump(mode="json")
    wire["fan_out"] = {"invented": 15}
    with pytest.raises(ValueError):
        type(report).model_validate(wire)
