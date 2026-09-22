"""Typing module aliases share mutations and lazy type aliases stay unevaluated."""

import pytest
from test_import_context_feedback import inspect, observations


@pytest.fixture(autouse=True)
def isolate_source_inventory(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


@pytest.mark.parametrize(
    "mutation",
    [
        "t.TYPE_CHECKING = True",
        "setattr(t, 'TYPE_CHECKING', True)",
    ],
)
def test_mutation_through_one_typing_alias_invalidates_guards_through_another(tmp_path, mutation):
    report = inspect(
        tmp_path,
        "import typing as t\nimport typing\n" + mutation + "\n"
        "if typing.TYPE_CHECKING:\n    import sample.storage\n",
    )
    edge = next(item for item in observations(report) if item.get("imported") == "sample.storage")
    assert edge["context"] == {"execution": "eager", "guards": ["conditional"]}


def test_lazy_type_alias_import_has_unknown_execution_context(tmp_path):
    report = inspect(tmp_path, "type Contract = __import__('lazy_alias_pkg')\n")
    imports = observations(report)
    assert len(imports) == 1
    assert imports[0]["state"] == "unresolved"
    assert "lazy_alias_pkg" in imports[0]["expression"]
    assert imports[0]["context"] == {"execution": "unknown", "guards": []}
    assert type(report).model_validate_json(report.model_dump_json()) == report
