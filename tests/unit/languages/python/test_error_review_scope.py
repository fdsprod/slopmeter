"""Executed declaration headers belong to the enclosing protected operation."""

from textwrap import dedent

import pytest

from slop_measure.domain.source import Cohort, ProjectPath, SourceDocument
from slop_measure.languages.python.error_review import analyze_errors


def inspect(source: str) -> dict:
    return analyze_errors(
        SourceDocument(
            path=ProjectPath("scope.py"),
            language="python",
            cohort=Cohort.PRODUCTION,
            content=dedent(source).encode(),
        )
    ).model_dump(mode="json")


def test_eager_declaration_headers_are_operations_but_nested_bodies_are_not() -> None:
    result = inspect("""\
        def work():
            try:
                @decorate(factory())
                def inner(value=default(), *, option=keyword_default()):
                    hidden_function()
                class Local(base(), metaclass=metaclass_factory()):
                    hidden_class()
                thunk = lambda value=lambda_default(): hidden_lambda()
                return result
            except Exception:
                return []
        """)
    (handler,) = result["handlers"]
    assert handler["state"] == "analyzed"
    (finding,) = handler["findings"]
    assert sorted(operation["expression"] for operation in finding["operations"]) == sorted(
        [
            "decorate(factory())",
            "factory()",
            "default()",
            "keyword_default()",
            "base()",
            "metaclass_factory()",
            "lambda_default()",
        ]
    )


@pytest.mark.parametrize("declaration", ["def inner():\n    pass", "class Local:\n    pass"])
def test_protected_span_starts_at_decorator_before_declaration(declaration: str) -> None:
    source = (
        "def work():\n    try:\n        @decorate()\n"
        + "".join(f"        {line}\n" for line in declaration.splitlines())
        + "        return result\n    except Exception:\n        return []\n"
    )
    (handler,) = inspect(source)["handlers"]
    assert handler["state"] == "analyzed"
    (finding,) = handler["findings"]
    assert finding["protected"] == dict(start_line=3, end_line=6)
    assert finding["operations"] == [
        dict(span=dict(start_line=3, end_line=3), expression="decorate()")
    ]


@pytest.mark.parametrize(
    "declaration",
    [
        "def inner(value=(yield 1)):\n    pass",
        "def inner(*, value=(yield 1)):\n    pass",
        "thunk = lambda value=(yield 1): None",
    ],
)
def test_yield_in_nested_callable_default_makes_enclosing_function_a_generator(
    declaration: str,
) -> None:
    source = (
        "def work():\n    try:\n"
        + "".join(f"        {line}\n" for line in declaration.splitlines())
        + "        return result\n    except Exception:\n        return []\n"
    )
    # Compilation checks the language construct without executing its source.
    compile(source, "scope.py", "exec")
    (handler,) = inspect(source)["handlers"]
    assert handler["state"] == "unresolved"
    assert "generator" in handler["reason"].lower()


@pytest.mark.parametrize(
    "declaration",
    [
        "type Alias = lazy_type()",
        "def inner[T: lazy_bound()]():\n    pass",
        "class Local[T: lazy_bound()]:\n    pass",
    ],
)
def test_lazy_type_expressions_are_not_invented_as_eager_protected_calls(
    declaration: str,
) -> None:
    source = (
        "def work():\n    try:\n"
        + "".join(f"        {line}\n" for line in declaration.splitlines())
        + "        return visible()\n    except Exception:\n        return []\n"
    )
    compile(source, "scope.py", "exec")
    (handler,) = inspect(source)["handlers"]
    if handler["state"] == "unresolved":
        reason = handler["reason"].lower()
        assert any(word in reason for word in ("type", "generic", "lazy", "scope"))
        return
    (finding,) = handler["findings"]
    assert [operation["expression"] for operation in finding["operations"]] == ["visible()"]
