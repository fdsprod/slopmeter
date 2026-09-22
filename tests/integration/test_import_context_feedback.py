"""Source import edges retain execution and guard context without runtime claims."""

import pytest
from test_architecture_review import policy, project
from typer.testing import CliRunner

from slop_measure import api
from slop_measure.cli import app


@pytest.fixture(autouse=True)
def isolate_source_inventory(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


def inspect(tmp_path, source, back_edge=""):
    selected = project(
        tmp_path,
        {
            "src/sample/__init__.py": "",
            "src/sample/controller.py": source,
            "src/sample/storage.py": back_edge,
        },
    )
    return api.inspect_architecture(selected, policy())


def observations(report):
    wire = report.model_dump(mode="json")
    return next(
        item["imports"] for item in wire["files"] if item["path"] == "src/sample/controller.py"
    )


@pytest.mark.parametrize(
    "source,execution,guards",
    [
        ("import sample.storage\n", "eager", []),
        ("class Controller:\n    import sample.storage\n", "eager", []),
        ("def load():\n    import sample.storage\n", "deferred", []),
        ("class Controller:\n    def load(self):\n        import sample.storage\n", "deferred", []),
        ("if enabled:\n    import sample.storage\n", "eager", ["conditional"]),
        (
            "def load():\n    if enabled:\n        import sample.storage\n",
            "deferred",
            ["conditional"],
        ),
        (
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import sample.storage\n",
            "eager",
            ["type-checking"],
        ),
        (
            "import typing as t\nif t.TYPE_CHECKING:\n    import sample.storage\n",
            "eager",
            ["type-checking"],
        ),
        (
            "from typing import TYPE_CHECKING as TC\nif TC:\n    import sample.storage\n",
            "eager",
            ["type-checking"],
        ),
        (
            "from typing import TYPE_CHECKING\ndef load():\n"
            "    if TYPE_CHECKING:\n        import sample.storage\n",
            "deferred",
            ["type-checking"],
        ),
        (
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
            "    if enabled:\n        import sample.storage\n",
            "eager",
            ["conditional", "type-checking"],
        ),
        (
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
            "    pass\nelse:\n    import sample.storage\n",
            "eager",
            ["conditional"],
        ),
    ],
)
@pytest.mark.xfail(strict=True, reason="Pending import execution contexts")
def test_internal_edges_retain_orthogonal_execution_and_guard_context(
    tmp_path, source, execution, guards
):
    report = inspect(tmp_path, source)
    edge = next(item for item in observations(report) if item.get("imported") == "sample.storage")

    assert edge["context"]["execution"] == execution
    assert set(edge["context"]["guards"]) == set(guards)
    assert len(report.violations) == 1
    assert report.fan_out["sample.controller"] == 1
    assert type(report).model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize(
    "source",
    [
        "TYPE_CHECKING = True\nif TYPE_CHECKING:\n    import sample.storage\n",
        "from typing import TYPE_CHECKING\nTYPE_CHECKING = True\n"
        "if TYPE_CHECKING:\n    import sample.storage\n",
        "import typing as t\nt = custom\nif t.TYPE_CHECKING:\n    import sample.storage\n",
        "from typing import TYPE_CHECKING\ndef load(TYPE_CHECKING):\n"
        "    if TYPE_CHECKING:\n        import sample.storage\n",
        "import typing as t\ndef load(t):\n"
        "    if t.TYPE_CHECKING:\n        import sample.storage\n",
        "from typing import TYPE_CHECKING\nclass Controller:\n    TYPE_CHECKING = True\n"
        "    if TYPE_CHECKING:\n        import sample.storage\n",
        "import typing\ntyping.TYPE_CHECKING = custom\n"
        "if typing.TYPE_CHECKING:\n    import sample.storage\n",
        "if TYPE_CHECKING:\n    import sample.storage\nfrom typing import TYPE_CHECKING\n",
        "if enabled:\n    from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n    import sample.storage\n",
    ],
)
@pytest.mark.xfail(strict=True, reason="Pending import execution contexts")
def test_shadowed_or_unbound_type_checking_names_remain_general_conditions(tmp_path, source):
    report = inspect(tmp_path, source)
    edge = next(item for item in observations(report) if item.get("imported") == "sample.storage")
    assert edge["context"]["guards"] == ["conditional"]


@pytest.mark.xfail(strict=True, reason="Pending import execution contexts")
def test_external_and_dynamic_imports_retain_the_same_deferred_type_only_context(tmp_path):
    source = (
        "from typing import TYPE_CHECKING\n"
        "def load():\n"
        "    if TYPE_CHECKING:\n"
        "        import remote_vendor\n"
        "        __import__('sample.storage')\n"
    )
    report = inspect(tmp_path, source)
    relevant = [item for item in observations(report) if item["span"]["start_line"] >= 4]
    assert {item["state"] for item in relevant} == {"external", "unresolved"}
    assert all(
        item["context"] == {"execution": "deferred", "guards": ["type-checking"]}
        for item in relevant
    )


@pytest.mark.xfail(strict=True, reason="Pending import execution contexts")
def test_type_only_and_deferred_edges_still_form_source_cycles(tmp_path):
    source = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import sample.storage\n"
    back_edge = "def load():\n    import sample.controller\n"
    report = inspect(tmp_path, source, back_edge)
    assert report.cycles == (("sample.controller", "sample.storage"),)
    contexts = {
        edge["importer"]: edge["context"] for edge in report.model_dump(mode="json")["edges"]
    }
    assert contexts["sample.controller"] == {"execution": "eager", "guards": ["type-checking"]}
    assert contexts["sample.storage"] == {"execution": "deferred", "guards": []}


@pytest.mark.xfail(strict=True, reason="Pending import execution contexts")
def test_old_reports_default_missing_import_context_to_unknown(tmp_path):
    report = inspect(
        tmp_path, "import sample.storage\nimport remote_vendor\n__import__('dynamic')\n"
    )
    wire = report.model_dump(mode="json")
    # Keep source evidence, then let the reader recompute all derived projections.
    for key in type(report).model_computed_fields:
        wire.pop(key, None)
    for file in wire["files"]:
        for item in file.get("imports", []):
            item.pop("context", None)
    restored = type(report).model_validate(wire)
    assert all(
        item["context"] == {"execution": "unknown", "guards": []} for item in observations(restored)
    )
    assert restored.fan_out == report.fan_out


@pytest.mark.xfail(strict=True, reason="Pending import execution contexts")
def test_full_old_report_with_computed_edges_and_violations_loads_unknown_context(tmp_path):
    report = inspect(tmp_path, "import sample.storage\n", "import sample.controller\n")
    wire = report.model_dump(mode="json")

    def remove_context(value):
        if isinstance(value, dict):
            value.pop("context", None)
            for child in value.values():
                remove_context(child)
        elif isinstance(value, list):
            for child in value:
                remove_context(child)

    remove_context(wire)
    assert wire["edges"] and wire["violations"] and wire["cycles"]
    restored = type(report).model_validate(wire)
    assert all(
        item["context"] == {"execution": "unknown", "guards": []} for item in observations(restored)
    )
    assert restored.cycles == report.cycles
    assert restored.fan_out == report.fan_out
    assert len(restored.violations) == 1


@pytest.mark.parametrize(
    "context",
    [
        {"execution": "sometimes", "guards": []},
        {"execution": "eager", "guards": ["invented"]},
        {"execution": "unknown", "guards": ["type-checking"]},
    ],
)
def test_import_context_rejects_unknown_values_and_invented_legacy_guards(tmp_path, context):
    report = inspect(tmp_path, "import sample.storage\n")
    wire = report.model_dump(mode="json")
    for key in type(report).model_computed_fields:
        wire.pop(key, None)
    for file in wire["files"]:
        for item in file.get("imports", []):
            item["context"] = context
    with pytest.raises(ValueError):
        type(report).model_validate(wire)


def test_function_definition_expressions_use_enclosing_execution_context(tmp_path):
    source = (
        "@decorate(__import__('decorator_pkg'))\n"
        "def load(client=__import__('default_pkg')):\n"
        "    return __import__('body_pkg')\n"
    )
    report = inspect(tmp_path, source)
    imports = observations(report)
    assert len(imports) == 3
    for package, expected in (
        ("decorator_pkg", "eager"),
        ("default_pkg", "eager"),
        ("body_pkg", "deferred"),
    ):
        occurrence = next(item for item in imports if package in item["expression"])
        assert occurrence["context"] == {"execution": expected, "guards": []}


def test_class_body_inside_function_remains_deferred(tmp_path):
    report = inspect(tmp_path, "def factory():\n    class Local:\n        import sample.storage\n")
    edge = next(item for item in observations(report) if item.get("imported") == "sample.storage")
    assert edge["context"] == {"execution": "deferred", "guards": []}


@pytest.mark.xfail(strict=True, reason="Pending generator outer iterable execution context")
def test_generator_outer_iterable_is_eager_but_body_and_filters_are_deferred(tmp_path):
    source = (
        "items = (__import__('body_pkg') for item in __import__('outer_pkg')\n"
        "         if __import__('filter_pkg'))\n"
    )
    report = inspect(tmp_path, source)
    imports = observations(report)
    assert len(imports) == 3
    for package, expected in (
        ("outer_pkg", "eager"),
        ("body_pkg", "deferred"),
        ("filter_pkg", "deferred"),
    ):
        occurrence = next(item for item in imports if package in item["expression"])
        assert occurrence["context"]["execution"] == expected


@pytest.mark.parametrize(
    "guard", ["not TYPE_CHECKING", "TYPE_CHECKING or enabled", "TYPE_CHECKING and enabled"]
)
def test_negative_and_compound_type_checking_guards_remain_general_conditions(tmp_path, guard):
    source = f"from typing import TYPE_CHECKING\nif {guard}:\n    import sample.storage\n"
    report = inspect(tmp_path, source)
    edge = next(item for item in observations(report) if item.get("imported") == "sample.storage")
    assert edge["context"] == {"execution": "eager", "guards": ["conditional"]}


def test_terminal_cycle_edges_show_owned_source_locations_and_execution_context(tmp_path):
    inspect(
        tmp_path,
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import sample.storage\n",
        "def load():\n    import sample.controller\n",
    )
    policy_file = tmp_path / "architecture.toml"
    policy_file.write_text('source_roots=["src"]\n', encoding="utf-8")
    result = CliRunner().invoke(
        app, ["architecture", "--root", str(tmp_path), "--policy", str(policy_file), "--lang", "py"]
    )
    assert result.exit_code == 0, result.output
    lines = result.stdout.lower().splitlines()
    assert any("controller.py:3" in line and "type-checking" in line for line in lines)
    assert any("storage.py:2" in line and "deferred" in line for line in lines)
    assert "cycle" in result.stdout.lower()
