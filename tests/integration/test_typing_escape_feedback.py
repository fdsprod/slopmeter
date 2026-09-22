"""Escaping the typing module removes proof that its flag is type-only."""

import json

import pytest
from test_architecture_review import policy, project
from test_import_context_feedback import inspect, observations
from typer.testing import CliRunner

from slop_measure import api
from slop_measure.cli import app


@pytest.fixture(autouse=True)
def isolate_source_inventory(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


@pytest.mark.parametrize("receiver", ["t", "typing"])
@pytest.mark.parametrize(
    "escape",
    [
        pytest.param("other = t\nother.TYPE_CHECKING = True", id="alias-mutation"),
        pytest.param("other = t", id="alias-without-observed-mutation"),
        pytest.param("first = other = t\nother.TYPE_CHECKING = True", id="chained-assignment"),
        pytest.param("other: object = t\nother.TYPE_CHECKING = True", id="annotated-assignment"),
        pytest.param("holder = [t]\nholder[0].TYPE_CHECKING = True", id="list-assignment"),
        pytest.param(
            "holder = {'module': t}\nholder['module'].TYPE_CHECKING = True",
            id="dictionary-assignment",
        ),
        pytest.param("holder = (t,)\nholder[0].TYPE_CHECKING = True", id="tuple-assignment"),
        pytest.param("unknown(t)", id="unknown-function-argument"),
        pytest.param("unknown(module=t)", id="unknown-keyword-argument"),
        pytest.param(
            "namespace = t.__dict__\nnamespace['TYPE_CHECKING'] = True",
            id="mutable-namespace-alias",
        ),
        pytest.param("unknown(t.__dict__)", id="mutable-namespace-argument"),
    ],
)
def test_typing_module_escape_invalidates_all_imported_module_aliases(tmp_path, receiver, escape):
    report = inspect(
        tmp_path,
        "import typing as t\nimport typing\n"
        + escape
        + f"\nif {receiver}.TYPE_CHECKING:\n    import sample.storage\n",
        "import sample.controller\n",
    )
    edge = next(item for item in observations(report) if item.get("imported") == "sample.storage")
    assert len(report.edges) == 2
    assert len(report.violations) == 1
    assert report.violations[0].edge.imported == "sample.storage"
    assert report.cycles == (("sample.controller", "sample.storage"),)
    assert report.fan_out["sample.controller"] == 1
    assert edge["context"] == {"execution": "eager", "guards": ["conditional"]}


@pytest.mark.parametrize(
    "source",
    [
        "import typing\nif typing.TYPE_CHECKING:\n    import sample.storage\n",
        "import typing as t\nother = object()\nother.TYPE_CHECKING = True\n"
        "if t.TYPE_CHECKING:\n    import sample.storage\n",
        "import typing as t\nother = t.Any\nif t.TYPE_CHECKING:\n    import sample.storage\n",
        "import typing as t\nother = t.Optional\nif t.TYPE_CHECKING:\n    import sample.storage\n",
        "import typing as t\nflag = t.TYPE_CHECKING\n"
        "if t.TYPE_CHECKING:\n    import sample.storage\n",
        "from typing import TYPE_CHECKING\nother = object()\n"
        "if TYPE_CHECKING:\n    import sample.storage\n",
        "from typing import TYPE_CHECKING as TC\nother = object()\n"
        "if TC:\n    import sample.storage\n",
    ],
)
def test_unescaped_typing_guards_keep_type_checking_context(tmp_path, source):
    report = inspect(tmp_path, source)
    edge = next(item for item in observations(report) if item.get("imported") == "sample.storage")
    assert edge["context"] == {"execution": "eager", "guards": ["type-checking"]}


def test_escaped_module_report_matches_cli_without_executing_or_changing_snapshot(tmp_path):
    marker = tmp_path / "target-executed"
    selected = project(
        tmp_path,
        {
            "src/sample/__init__.py": "",
            "src/sample/controller.py": (
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).touch()\n"
                "import typing as t\nother = t\nother.TYPE_CHECKING = True\n"
                "if t.TYPE_CHECKING:\n    import sample.storage\n"
            ),
            "src/sample/storage.py": "import sample.controller\n",
        },
    )
    config = tmp_path / "architecture.toml"
    config.write_text(
        'source_roots=["src"]\n[[forbidden]]\nsource="sample.controller"\ntarget="sample.storage"\n',
        encoding="utf-8",
    )
    before = api.scan(selected)
    report = api.inspect_architecture(selected, policy())
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
    assert not marker.exists()
    assert api.scan(selected).cohorts == before.cohorts
    assert json.loads(result.stdout) == report.model_dump(mode="json")
    assert report.cycles == (("sample.controller", "sample.storage"),)
    assert len(report.violations) == 1
    assert report.violations[0].edge.context.model_dump(mode="json") == {
        "execution": "eager",
        "guards": ["conditional"],
    }
