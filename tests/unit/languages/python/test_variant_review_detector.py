"""Typed local match review reports syntactic coverage and explicit uncertainty."""

import hashlib

import pytest

from slop_measure.domain.source import Cohort, ProjectPath, SourceDocument
from slop_measure.languages.python.variant_review import analyze_variants

PREFIX = "from enum import Enum\nclass Color(Enum):\n    RED = 1\n    BLUE = 2\n"


def inspect(source: str) -> dict:
    document = SourceDocument(
        path=ProjectPath("variants.py"),
        language="python",
        cohort=Cohort.PRODUCTION,
        content=source.encode("utf-8"),
    )
    return analyze_variants(document).model_dump(mode="json")


def handler(cases: str, *, prefix: str = PREFIX, annotation: str = "Color") -> str:
    return prefix + f"def render(value: {annotation}):\n    match value:\n" + cases


@pytest.mark.parametrize(
    "cases,coverage,unhandled",
    [
        ("        case Color.RED:\n            return 1\n", "missing", ["Color.BLUE"]),
        ("        case Color.RED | Color.BLUE:\n            return 1\n", "exhaustive", []),
        (
            "        case Color.RED if allowed:\n            return 1\n",
            "missing",
            ["Color.RED", "Color.BLUE"],
        ),
        (
            "        case Color.RED:\n            return 1\n"
            "        case _:\n            return 0\n",
            "fallback",
            ["Color.BLUE"],
        ),
        (
            "        case Color.RED:\n            return 1\n"
            "        case _ if allowed:\n            return 0\n",
            "missing",
            ["Color.BLUE"],
        ),
        (
            "        case remaining:\n            return 0\n",
            "fallback",
            ["Color.RED", "Color.BLUE"],
        ),
    ],
)
def test_coverage_distinguishes_explicit_conditional_and_fallback_branches(
    cases: str, coverage: str, unhandled: list[str]
) -> None:
    source = handler(cases) + '\nraise RuntimeError("source must not execute")\n'
    outcome = inspect(source)
    assert outcome["state"] == "analyzed" and outcome["path"] == "variants.py"
    assert outcome["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    (result,) = outcome["handlers"]
    assert result["state"] == "analyzed" and result["symbol"] == "render"
    assert result["subject"] == "value" and result["span"]["start_line"] == 6
    assert result["coverage"] == coverage and result["not_explicitly_covered"] == unhandled
    assert result["declaration"] == {
        "name": "Color",
        "kind": "enum",
        "span": {"start_line": 2, "end_line": 4},
        "cases": [
            {"name": "Color.RED", "span": {"start_line": 3, "end_line": 3}},
            {"name": "Color.BLUE", "span": {"start_line": 4, "end_line": 4}},
        ],
    }
    assert result["branches"][0]["span"]["start_line"] == 7
    assert result["branches"][0]["conditional"] is ("if allowed" in cases.splitlines()[0])
    if "case remaining" in cases:
        assert result["branches"][0]["kind"] == "fallback"
        assert "cases" not in result["branches"][0]


@pytest.mark.parametrize("base", ["IntEnum", "StrEnum"])
def test_direct_import_alias_and_auto_values_preserve_local_case_names(base: str) -> None:
    prefix = (
        f"from enum import {base} as Finite, auto as next_value\n"
        "class Color(Finite):\n    RED = next_value()\n    BLUE = next_value()\n"
    )
    result = inspect(
        handler(
            "        case Color.RED:\n            return 1\n", prefix=prefix, annotation='"Color"'
        )
    )["handlers"][0]
    assert result["state"] == "analyzed" and result["not_explicitly_covered"] == ["Color.BLUE"]


@pytest.mark.parametrize(
    "declaration",
    [
        "Choice = Finite['open', 'closed']",
        "Choice: TypeAlias = Finite['open', 'closed']",
        "type Choice = Finite['open', 'closed']",
    ],
)
def test_named_literal_forms_use_repr_names_and_track_omitted_values(declaration: str) -> None:
    prefix = "from typing import Literal as Finite, TypeAlias\n" + declaration + "\n"
    source = handler(
        "        case 'open':\n            return 1\n", prefix=prefix, annotation="Choice"
    )
    result = inspect(source)["handlers"][0]
    assert result["state"] == "analyzed" and result["coverage"] == "missing"
    assert result["declaration"]["kind"] == "literal"
    assert [case["name"] for case in result["declaration"]["cases"]] == ["'open'", "'closed'"]
    assert result["not_explicitly_covered"] == ["'closed'"]


@pytest.mark.parametrize(
    "uncertainty",
    [
        "default-rebind",
        "shadowed-import",
        "reassigned-subject",
        "variadic",
        "decorated",
        "nested",
        "unsupported-pattern",
        "untyped",
    ],
)
def test_uncertain_match_bindings_are_unresolved_instead_of_silently_omitted(
    uncertainty: str,
) -> None:
    source = handler("        case Color.RED:\n            return 1\n")
    if uncertainty == "default-rebind":
        source = source.replace(
            "def render", "def configure(x=(Color := replacement)):\n    pass\ndef render"
        )
    elif uncertainty == "shadowed-import":
        source = source.replace("class Color", "from foreign import Enum\nclass Color")
    elif uncertainty == "reassigned-subject":
        source = source.replace("    match value:", "    value = replacement\n    match value:")
    elif uncertainty == "variadic":
        source = source.replace("value: Color", "*value: Color")
    elif uncertainty == "decorated":
        source = source.replace("def render", "@transform\ndef render")
    elif uncertainty == "nested":
        head, function = source.split("def render", 1)
        source = (
            head
            + "def outer():\n"
            + "\n".join("    " + line for line in ("def render" + function).splitlines())
            + "\n"
        )
    elif uncertainty == "unsupported-pattern":
        source = source.replace("case Color.RED:", "case [first, second]:")
    else:
        source = source.replace("value: Color", "value")
    outcome = inspect(source)
    assert outcome["state"] == "analyzed" and len(outcome["handlers"]) == 1
    result = outcome["handlers"][0]
    assert result["state"] == "unresolved" and result["reason"].strip()
    assert "coverage" not in result and "not_explicitly_covered" not in result


@pytest.mark.parametrize("invalid", ["enum-alias", "enum-dynamic", "literal-duplicate"])
def test_unproven_finite_vocabularies_are_unresolved(invalid: str) -> None:
    prefix = PREFIX
    annotation = "Color"
    pattern = "Color.RED"
    if invalid == "enum-alias":
        prefix = prefix.replace("BLUE = 2", "BLUE = 1")
    elif invalid == "enum-dynamic":
        prefix = prefix.replace("BLUE = 2", "BLUE = produce_value()")
    else:
        prefix = "from typing import Literal\nChoice = Literal[1, 1]\n"
        annotation, pattern = "Choice", "1"
    result = inspect(
        handler(
            f"        case {pattern}:\n            return 1\n", prefix=prefix, annotation=annotation
        )
    )["handlers"][0]
    assert result["state"] == "unresolved" and result["reason"]


def test_parse_failure_is_failed_not_an_empty_clean_handler_list() -> None:
    outcome = inspect("def broken(:\n")
    assert outcome["state"] == "failed"
    assert outcome["diagnostic"]["path"] == "variants.py"
    assert outcome["diagnostic"]["severity"] == "error"
    assert "handlers" not in outcome


@pytest.mark.parametrize("invalid", ["str-auto-collision", "int-enum-string", "str-enum-integer"])
def test_enum_runtime_invalid_or_aliasing_values_are_not_finite_evidence(invalid: str) -> None:
    if invalid == "str-auto-collision":
        prefix = (
            "from enum import StrEnum, auto\n"
            "class Color(StrEnum):\n    A = auto()\n    a = auto()\n"
        )
        pattern = "Color.A"
    elif invalid == "int-enum-string":
        prefix = (
            "from enum import IntEnum\nclass Color(IntEnum):\n    RED = 'red'\n    BLUE = 'blue'\n"
        )
        pattern = "Color.RED"
    else:
        prefix = "from enum import StrEnum\nclass Color(StrEnum):\n    RED = 1\n    BLUE = 2\n"
        pattern = "Color.RED"
    result = inspect(handler(f"        case {pattern}:\n            return 1\n", prefix=prefix))[
        "handlers"
    ][0]
    assert result["state"] == "unresolved" and result["reason"]


def test_unconditional_catch_all_before_later_case_is_unresolved_not_exhaustive() -> None:
    source = handler(
        "        case _:\n            return 0\n        case Color.RED:\n            return 1\n"
    )
    result = inspect(source)["handlers"][0]
    assert result["state"] == "unresolved" and result["reason"]
    assert "coverage" not in result


def test_literal_alias_rebound_by_function_default_is_unresolved() -> None:
    prefix = "from typing import Literal\nChoice = Literal['open', 'closed']\n"
    prefix += "def configure(value=(Choice := replacement)):\n    pass\n"
    result = inspect(
        handler("        case 'open':\n            return 1\n", prefix=prefix, annotation="Choice")
    )["handlers"][0]
    assert result["state"] == "unresolved" and result["reason"]


def test_variadic_keyword_subject_is_a_container_not_the_annotated_variant() -> None:
    source = handler("        case Color.RED:\n            return 1\n").replace(
        "value: Color", "**value: Color"
    )
    result = inspect(source)["handlers"][0]
    assert result["state"] == "unresolved" and result["reason"]
