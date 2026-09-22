"""Change surface counts source declarations without judging engineering quality."""

import json
from hashlib import sha256
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slop_measure import api
from slop_measure.api import AnalysisConfig, ComparisonRequest, DirectorySourceReference
from slop_measure.cli import app


def comparison(
    tmp_path: Path, baseline: dict[str, str], current: dict[str, str]
) -> ComparisonRequest:
    for side, files in (("baseline", baseline), ("current", current)):
        root = tmp_path / side
        root.mkdir()
        for name, source in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8", newline="")
    return ComparisonRequest(
        baseline=DirectorySourceReference(root=tmp_path / "baseline"),
        current=DirectorySourceReference(root=tmp_path / "current"),
        config=AnalysisConfig(languages=frozenset({"python"})),
    )


def test_added_modified_removed_and_unchanged_symbols_have_separate_counts(tmp_path):
    new_source = "def fresh():\n    return 5\n"
    request = comparison(
        tmp_path,
        {
            "changed.py": "def existing():\n    return 1\n",
            "retired.py": "def retired():\n    return None\n",
            "stable.py": "def stable():\n    return True\n",
        },
        {
            "changed.py": "def existing():\n    return 2\n",
            "new.py": new_source,
            "stable.py": "def stable():\n    return True\n",
        },
    )

    report = api.review_surface(request)

    assert report.summary == {
        "added": 1,
        "removed": 1,
        "modified": 1,
        "moved": 0,
        "unchanged": 1,
        "unresolved": 0,
    }
    assert report.file_summary == {
        "added": 1,
        "deleted": 1,
        "modified": 1,
        "renamed": 0,
        "unchanged": 1,
        "unresolved": 0,
    }
    assert report.novel_ratio.state == "measured"
    assert report.novel_ratio.value == 0.5
    added = next(item.current for item in report.symbols if item.state == "added")
    assert added.qualified_name == "fresh"
    assert added.kind == "function"
    assert added.path.root == "new.py"
    assert (added.span.start_line, added.span.end_line) == (1, 2)
    assert added.source_sha256 == sha256(new_source.encode()).hexdigest()
    assert len(added.ast_fingerprint) == 64
    assert int(added.ast_fingerprint, 16) >= 0
    assert report.analysis.baseline.root == request.baseline.root.resolve()
    assert report.analysis.current.root == request.current.root.resolve()
    assert report.provenance.tool_version
    assert "score" not in report.model_dump(mode="json")


def test_blank_lines_comments_and_formatting_do_not_add_symbol_surface(tmp_path):
    request = comparison(
        tmp_path,
        {"sample.py": "def parse(value):\n    return value + 1\n"},
        {"sample.py": "# context\n\ndef parse( value ):\n    return (value+1)\n"},
    )

    report = api.review_surface(request)

    assert report.summary["unchanged"] == 1
    assert report.summary["modified"] == report.summary["added"] == 0
    change = report.symbols[0]
    assert change.state == "unchanged"
    assert change.baseline.ast_fingerprint == change.current.ast_fingerprint
    assert change.baseline.source_sha256 != change.current.source_sha256
    assert change.baseline.span.start_line == 1
    assert change.current.span.start_line == 3
    assert report.novel_ratio.state == "unavailable"
    assert report.novel_ratio.reason == "no-added-or-modified-symbols"


def test_unique_whole_symbol_move_is_excluded_from_novel_ratio(tmp_path):
    request = comparison(
        tmp_path,
        {"old.py": "# old module\ndef reused(value):\n    return value\n"},
        {"new.py": "# new module\n\ndef reused(value):\n    return value\n"},
    )

    report = api.review_surface(request)

    assert report.summary["moved"] == 1
    assert report.summary["added"] == report.summary["removed"] == 0
    moved = next(item for item in report.symbols if item.state == "moved")
    assert moved.baseline.path.root == "old.py"
    assert moved.current.path.root == "new.py"
    assert moved.baseline.ast_fingerprint == moved.current.ast_fingerprint
    assert report.novel_ratio.state == "unavailable"


def test_classes_methods_async_functions_and_nested_declarations_are_source_bound(tmp_path):
    request = comparison(
        tmp_path,
        {"sample.py": ""},
        {
            "sample.py": (
                "class Box:\n"
                "    def read(self):\n"
                "        return 1\n"
                "\n"
                "async def outer():\n"
                "    def inner():\n"
                "        return 2\n"
                "    return inner()\n"
            )
        },
    )

    report = api.review_surface(request)

    assert {
        (item.current.kind, item.current.qualified_name)
        for item in report.symbols
        if item.state == "added"
    } == {
        ("class", "Box"),
        ("function", "Box.read"),
        ("function", "outer"),
        ("function", "outer.inner"),
    }
    assert report.summary["added"] == 4
    assert report.novel_ratio.state == "measured"
    assert report.novel_ratio.value == 1.0


def test_declaration_rename_does_not_invent_added_and_removed_symbols(tmp_path):
    request = comparison(
        tmp_path,
        {"sample.py": "def old_name(value):\n    return value\n"},
        {"sample.py": "def new_name(value):\n    return value\n"},
    )

    report = api.review_surface(request)

    assert report.summary["added"] == report.summary["removed"] == 0
    unresolved = next(item for item in report.symbols if item.state == "unresolved")
    assert [item.qualified_name for item in unresolved.baseline] == ["old_name"]
    assert [item.qualified_name for item in unresolved.current] == ["new_name"]
    assert unresolved.reason


def test_competing_move_candidates_remain_unresolved(tmp_path):
    source = "def reused():\n    return 1\n"
    request = comparison(tmp_path, {"old.py": source}, {"one.py": source, "two.py": source})

    report = api.review_surface(request)

    assert report.summary["added"] == report.summary["moved"] == report.summary["removed"] == 0
    unresolved = next(item for item in report.symbols if item.state == "unresolved")
    assert len(unresolved.baseline) == 1
    assert {item.path.root for item in unresolved.current} == {"one.py", "two.py"}
    assert unresolved.reason


def test_duplicate_qualified_names_are_not_arbitrarily_paired(tmp_path):
    source = "def repeated():\n    return 1\n\ndef repeated():\n    return 2\n"
    request = comparison(tmp_path, {"sample.py": source}, {"sample.py": source})

    report = api.review_surface(request)

    assert report.summary["unresolved"] >= 1
    assert report.summary["unchanged"] == 0
    unresolved = next(item for item in report.symbols if item.state == "unresolved")
    assert len(unresolved.baseline) == len(unresolved.current) == 2


def test_parse_failure_is_not_reported_as_symbol_removal(tmp_path):
    request = comparison(
        tmp_path,
        {"sample.py": "def kept():\n    return 1\n"},
        {"sample.py": "def kept(:\n"},
    )

    report = api.review_surface(request)

    assert report.summary["removed"] == report.summary["added"] == 0
    assert report.summary["unresolved"] >= 1
    assert report.limitations
    assert any(
        item.source.value == "current"
        and item.detail.path is not None
        and item.detail.path.root == "sample.py"
        for item in report.diagnostics
    )


def test_empty_declaration_population_has_no_novel_ratio(tmp_path):
    request = comparison(tmp_path, {"sample.py": "value = 1\n"}, {"sample.py": "value = 2\n"})

    report = api.review_surface(request)

    assert report.symbols == ()
    assert all(count == 0 for count in report.summary.values())
    assert report.novel_ratio.state == "unavailable"
    assert report.novel_ratio.reason == "no-added-or-modified-symbols"


def test_surface_report_roundtrips_and_rejects_invented_counts(tmp_path):
    request = comparison(tmp_path, {}, {"sample.py": "def added():\n    return 1\n"})
    report = api.review_surface(request)
    assert type(report).model_validate_json(report.model_dump_json()) == report
    assert api.review_surface(request).model_dump_json() == report.model_dump_json()
    wire = report.model_dump(mode="json")
    wire["summary"]["added"] = 99
    with pytest.raises(ValueError):
        type(report).model_validate(wire)


def test_surface_cli_emits_the_api_report(tmp_path):
    request = comparison(
        tmp_path,
        {"sample.py": "def existing():\n    return 1\n"},
        {"sample.py": "def existing():\n    return 2\n"},
    )
    result = CliRunner().invoke(
        app,
        [
            "surface",
            str(request.baseline.root),
            str(request.current.root),
            "--lang",
            "py",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == api.review_surface(request).model_dump(mode="json")
