"""Unresolved match evidence explains the failed proof without changing eligibility."""

import json
from pathlib import Path
from textwrap import indent

import pytest
from typer.testing import CliRunner

from slop_measure.cli import app
from slop_measure.domain.source import Cohort, ProjectPath, SourceDocument
from slop_measure.languages.python.variant_review import analyze_variants

PREFIX = "from enum import Enum\nclass Color(Enum):\n    RED = 1\n    BLUE = 2\n"
FUNCTION = (
    "def render(value: Color):\n    match value:\n        case Color.RED:\n            return 1\n"
)
SOURCE = PREFIX + FUNCTION


def inspect(source: str) -> dict:
    document = SourceDocument(
        path=ProjectPath("variants.py"),
        language="python",
        cohort=Cohort.PRODUCTION,
        content=source.encode("utf-8"),
    )
    result = analyze_variants(document).model_dump(mode="json")
    assert result["state"] == "analyzed"
    (handler,) = result["handlers"]
    return handler


@pytest.mark.parametrize(
    "source,fragments",
    [
        pytest.param(
            PREFIX + "def outer():\n" + indent(FUNCTION, "    "),
            ("top-level",),
            id="nested-function",
        ),
        pytest.param(
            PREFIX + "class Renderer:\n" + indent(FUNCTION, "    "),
            ("top-level",),
            id="method",
        ),
        pytest.param(
            PREFIX + "match value:\n    case Color.RED:\n        pass\n",
            ("top-level",),
            id="module-match",
        ),
        pytest.param(
            SOURCE.replace("def render", "@transform\ndef render"),
            ("decorat",),
            id="decorated-function",
        ),
        pytest.param(
            SOURCE.replace("def render(", "def render[T]("),
            ("type parameter",),
            id="type-parameters",
        ),
        pytest.param(
            SOURCE.replace("    match value:", "    prepare()\n    match value:"),
            ("first",),
            id="nonleading-match",
        ),
        pytest.param(
            SOURCE.replace("match value:", "match value.color:"),
            ("subject", "name"),
            id="attribute-subject",
        ),
        pytest.param(
            SOURCE.replace("def render(value: Color)", "def render(other: Color)"),
            ("subject", "parameter"),
            id="subject-not-parameter",
        ),
        pytest.param(
            SOURCE.replace("value: Color", "*value: Color"),
            ("variadic",),
            id="variadic-subject",
        ),
        pytest.param(
            SOURCE.replace("value: Color", "value"),
            ("annotation", "missing"),
            id="missing-annotation",
        ),
        pytest.param(
            SOURCE.replace("value: Color", "value: Color | None"),
            ("annotation", "unsupported"),
            id="unsupported-annotation",
        ),
        pytest.param(
            "from foreign import *\n" + SOURCE,
            ("binding", "uncertain", "module"),
            id="uncertain-module-binding",
        ),
        pytest.param(
            SOURCE + "    exec('value = replacement')\n",
            ("binding", "uncertain", "local"),
            id="uncertain-local-binding",
        ),
        pytest.param(
            SOURCE + "render = replacement\n",
            ("binding", "render"),
            id="rebound-function",
        ),
        pytest.param(
            SOURCE + "    value = replacement\n",
            ("binding", "value"),
            id="rebound-subject",
        ),
        pytest.param(
            SOURCE + "    Color = replacement\n",
            ("binding", "color"),
            id="rebound-local-annotation",
        ),
        pytest.param(
            SOURCE + "Color = replacement\n",
            ("binding", "color"),
            id="rebound-declaration",
        ),
        pytest.param(
            FUNCTION,
            ("declaration", "color"),
            id="missing-declaration",
        ),
        pytest.param(
            SOURCE.replace("BLUE = 2", "BLUE = compute_value()"),
            ("supported local declaration", "color"),
            id="unsupported-declaration",
        ),
        pytest.param(
            "from external import Color\n" + FUNCTION,
            ("supported local declaration", "color"),
            id="imported-declaration",
        ),
        pytest.param(
            SOURCE.replace("case Color.RED:", "case [first, second]:"),
            ("pattern", "[first, second]"),
            id="sequence-pattern",
        ),
        pytest.param(
            SOURCE.replace("case Color.RED:", "case Color.GREEN:"),
            ("pattern", "color.green"),
            id="unknown-case",
        ),
        pytest.param(
            SOURCE.replace(
                "        case Color.RED:",
                "        case _:\n            return 0\n        case Color.RED:",
            ),
            ("catch-all", "last"),
            id="premature-fallback",
        ),
    ],
)
def test_unresolved_reason_names_the_specific_failed_proof(
    source: str, fragments: tuple[str, ...]
) -> None:
    handler = inspect(source)
    assert handler["state"] == "unresolved"
    assert "coverage" not in handler and "branches" not in handler
    reason = handler["reason"].lower()
    for fragment in fragments:
        assert fragment in reason, reason


@pytest.mark.parametrize(
    "cases,coverage,missing",
    [
        ("Color.RED", "missing", ["Color.BLUE"]),
        ("Color.RED | Color.BLUE", "exhaustive", []),
        ("_", "fallback", ["Color.RED", "Color.BLUE"]),
    ],
)
def test_supported_handlers_keep_their_complete_evidence(
    cases: str, coverage: str, missing: list[str]
) -> None:
    handler = inspect(SOURCE.replace("case Color.RED:", f"case {cases}:"))
    assert handler == {
        "state": "analyzed",
        "symbol": "render",
        "subject": "value",
        "span": {"start_line": 6, "end_line": 8},
        "declaration": {
            "name": "Color",
            "kind": "enum",
            "span": {"start_line": 2, "end_line": 4},
            "cases": [
                {"name": "Color.RED", "span": {"start_line": 3, "end_line": 3}},
                {"name": "Color.BLUE", "span": {"start_line": 4, "end_line": 4}},
            ],
        },
        "branches": [
            {
                "kind": "fallback" if cases == "_" else "cases",
                "span": {"start_line": 7, "end_line": 7},
                "conditional": False,
                **({} if cases == "_" else {"cases": cases.split(" | ")}),
            }
        ],
        "not_explicitly_covered": missing,
        "coverage": coverage,
    }


def test_specific_reason_reaches_json_and_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    (tmp_path / "variants.py").write_text(SOURCE.replace("value: Color", "value"), encoding="utf-8")
    runner = CliRunner()
    args = ["variants", "--root", str(tmp_path)]
    wire = runner.invoke(app, [*args, "--json"])
    plain = runner.invoke(app, args)
    assert wire.exit_code == plain.exit_code == 0
    handler = json.loads(wire.stdout)["files"][0]["handlers"][0]
    reason = handler["reason"]
    assert handler["state"] == "unresolved"
    assert "missing" in reason.lower() and "annotation" in reason.lower()
    assert reason in plain.stdout
    assert "variants.py:6" in plain.stdout and "render" in plain.stdout
