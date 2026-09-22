"""Exception fallbacks retain source evidence without claiming business intent."""

import hashlib
from textwrap import dedent

import pytest

from slop_measure.domain.source import Cohort, ProjectPath, SourceDocument
from slop_measure.languages.python.error_review import analyze_errors


def inspect(source: str) -> dict:
    return analyze_errors(
        SourceDocument(
            path=ProjectPath("errors.py"),
            language="python",
            cohort=Cohort.PRODUCTION,
            content=source.encode(),
        )
    ).model_dump(mode="json")


def function(body: str) -> str:
    return "def work():\n" + "".join(f"    {line}\n" for line in body.splitlines())


def handler_source(body: str, *, caught: str = "Exception", normal: str = "result") -> str:
    clause = f"except {caught}:" if caught else "except:"
    handler = "\n".join(f"    {line}" for line in body.splitlines())
    return function(f"try:\n    result = load()\n{clause}\n{handler}\nreturn {normal}")


def test_candidate_preserves_exact_source_evidence_and_normalized_expressions() -> None:
    source = (
        "def work():\n"
        "    try:\n"
        "        result = fetch( 'users' )\n"
        "        audit(result)\n"
        "        return result\n"
        "    except (OSError, service.Timeout) as exc:\n"
        "        logger.warning('load failed', exc_info=exc)\n"
        "        return []\n"
    )
    result = inspect(source)
    assert result["state"] == "analyzed"
    assert result["path"] == "errors.py" and result["cohort"] == "production"
    assert result["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    (handler,) = result["handlers"]
    assert handler["state"] == "analyzed" and handler["symbol"] == "work"
    assert handler["span"] == dict(start_line=6, end_line=8)
    assert handler["findings"] == [
        dict(
            kind="error-as-success",
            caught="(OSError, service.Timeout)",
            protected=dict(start_line=3, end_line=5),
            operations=[
                dict(span=dict(start_line=3, end_line=3), expression="fetch('users')"),
                dict(span=dict(start_line=4, end_line=4), expression="audit(result)"),
            ],
            fallback=dict(span=dict(start_line=8, end_line=8), expression="[]"),
            fallback_kind="empty-list",
            normal_returns=[dict(span=dict(start_line=5, end_line=5), expression="result")],
        )
    ]


@pytest.mark.parametrize(
    "statement,kind",
    [
        ("return", "none"),
        ("return None", "none"),
        ("return False", "false"),
        ("return 0", "zero"),
        ("return 0.0", "zero"),
        ("return ''", "empty-string"),
        ("return b''", "empty-bytes"),
        ("return []", "empty-list"),
        ("return {}", "empty-dict"),
        ("return ()", "empty-tuple"),
    ],
)
def test_literal_defaults_are_review_candidates_with_corroboration(
    statement: str, kind: str
) -> None:
    handler = inspect(handler_source(statement))["handlers"][0]
    assert handler["state"] == "analyzed"
    (finding,) = handler["findings"]
    assert finding["fallback_kind"] == kind
    assert finding["normal_returns"][0]["expression"] == "result"


@pytest.mark.parametrize("caught", ["", "MissingRecord", "custom.Exception", "(A, B)"])
def test_exception_spelling_is_supported_without_builtin_or_inheritance_resolution(
    caught: str,
) -> None:
    handler = inspect(handler_source("return []", caught=caught))["handlers"][0]
    assert handler["state"] == "analyzed"
    assert len(handler["findings"]) == 1
    assert handler["findings"][0]["caught"]
    if caught:
        assert handler["findings"][0]["caught"] == caught


@pytest.mark.parametrize(
    "body",
    [
        "raise",
        "raise DomainError('failed')",
        "pass",
        "log_failure()",
        "return {'ok': False}",
        "return [1]",
        "return True",
        "return 7",
    ],
)
def test_reraise_no_return_and_explicit_nondefault_results_are_assessed(body: str) -> None:
    handler = inspect(handler_source(body))["handlers"][0]
    assert handler["state"] == "analyzed" and handler["findings"] == []


@pytest.mark.parametrize("normal", ["None", "False", "0", "''", "b''", "[]", "{}", "()"])
def test_intentional_default_only_function_has_no_corroborating_success(normal: str) -> None:
    handler = inspect(handler_source("return []", normal=normal))["handlers"][0]
    assert handler["state"] == "analyzed" and handler["findings"] == []


def test_no_explicit_normal_return_is_assessed_without_a_finding() -> None:
    source = function("try:\n    load()\nexcept Exception:\n    return []")
    handler = inspect(source)["handlers"][0]
    assert handler["state"] == "analyzed" and handler["findings"] == []


def test_logging_assignment_and_pass_do_not_explain_away_a_fallback() -> None:
    handler = inspect(handler_source("log_failure()\nseen = True\npass\nreturn []"))["handlers"][0]
    assert handler["state"] == "analyzed" and len(handler["findings"]) == 1


@pytest.mark.parametrize(
    "body,reason",
    [
        ("if retry:\n    return []\nreturn []", "control"),
        ("return []\nreturn []", "exit"),
        ("raise\nreturn []", "exit"),
        ("fallback = []\nreturn fallback", "indirect"),
        ("return defaults.empty", "indirect"),
        ("return Failure(error)", "indirect"),
        ("return set()", "indirect"),
    ],
)
def test_unsupported_handler_flow_has_a_specific_reason(body: str, reason: str) -> None:
    handler = inspect(handler_source(body))["handlers"][0]
    assert handler["state"] == "unresolved"
    assert reason in handler["reason"].lower()
    assert "findings" not in handler


@pytest.mark.parametrize("caught", ["exception_type()", "exceptions[0]"])
def test_dynamic_exception_expression_is_unresolved(caught: str) -> None:
    handler = inspect(handler_source("return []", caught=caught))["handlers"][0]
    assert handler["state"] == "unresolved" and "exception" in handler["reason"].lower()


@pytest.mark.parametrize(
    "source",
    [
        function(
            "try:\n    return load()\nexcept Exception:\n    return []\nfinally:\n    return 1"
        ),
        function(
            "try:\n    try:\n        return load()\n    except Exception:\n"
            "        return []\nfinally:\n    return 1"
        ),
    ],
)
def test_own_or_enclosing_finally_can_override_fallback_and_stays_unresolved(source: str) -> None:
    handler = inspect(source)["handlers"][0]
    assert handler["state"] == "unresolved" and "finally" in handler["reason"].lower()


@pytest.mark.parametrize("yield_statement", ["yield result", "yield from result"])
def test_generator_function_handlers_are_unresolved(yield_statement: str) -> None:
    source = handler_source("return []") + f"    {yield_statement}\n"
    handler = inspect(source)["handlers"][0]
    assert handler["state"] == "unresolved" and "generator" in handler["reason"].lower()


def test_except_star_is_unresolved_even_without_a_return() -> None:
    source = function("try:\n    result = load()\nexcept* Exception:\n    pass\nreturn result")
    handler = inspect(source)["handlers"][0]
    assert handler["state"] == "unresolved"
    assert "except*" in handler["reason"]


@pytest.mark.parametrize("prefix", ["", "class Container:\n"])
def test_handlers_outside_functions_are_counted_as_unresolved(prefix: str) -> None:
    source = "try:\n    load()\nexcept Exception:\n    pass\n"
    if prefix:
        source = prefix + "".join(f"    {line}\n" for line in source.splitlines())
    (handler,) = inspect(source)["handlers"]
    assert handler["state"] == "unresolved" and handler["reason"]


def test_async_methods_and_nested_functions_keep_their_lexical_symbols() -> None:
    source = dedent("""\
        class Client:
            async def fetch(self):
                try:
                    return await load()
                except OSError:
                    return []
            def outer(self):
                def inner():
                    try:
                        return load()
                    except OSError:
                        return None
                try:
                    load()
                except OSError:
                    return []
        """)
    handlers = {item["symbol"]: item for item in inspect(source)["handlers"]}
    assert set(handlers) == {"Client.fetch", "Client.outer", "Client.outer.inner"}
    assert len(handlers["Client.fetch"]["findings"]) == 1
    assert len(handlers["Client.outer.inner"]["findings"]) == 1
    assert handlers["Client.outer"]["findings"] == []


def test_handler_returns_do_not_corroborate_other_handlers() -> None:
    source = function("try:\n    load()\nexcept A:\n    return []\nexcept B:\n    return 1")
    handlers = inspect(source)["handlers"]
    assert len(handlers) == 2
    assert all(handler["state"] == "analyzed" and not handler["findings"] for handler in handlers)


def test_nested_bodies_and_exception_handlers_do_not_pollute_protected_operations() -> None:
    source = function(
        "try:\n    def inner():\n        return hidden()\n    class Local:\n"
        "        value = hidden_class()\n    thunk = lambda: hidden_lambda()\n"
        "    try:\n        visible()\n    except A:\n        hidden_handler()\n"
        "    return result\nexcept B:\n    return []"
    )
    handlers = inspect(source)["handlers"]
    assert len(handlers) == 2
    finding = next(item["findings"][0] for item in handlers if item["findings"])
    assert [operation["expression"] for operation in finding["operations"]] == ["visible()"]
    assert [normal["expression"] for normal in finding["normal_returns"]] == ["result"]


def test_nested_generator_does_not_turn_parent_function_into_a_generator() -> None:
    source = function(
        "def events():\n    yield event\ntry:\n    return load()\nexcept Exception:\n    return []"
    )
    (handler,) = inspect(source)["handlers"]
    assert handler["state"] == "analyzed" and len(handler["findings"]) == 1


def test_finally_in_an_enclosing_function_does_not_override_nested_function_returns() -> None:
    source = function(
        "try:\n    def inner():\n        try:\n            return load()\n"
        "        except Exception:\n            return []\nfinally:\n    cleanup()"
    )
    (handler,) = inspect(source)["handlers"]
    assert handler["symbol"] == "work.inner"
    assert handler["state"] == "analyzed" and len(handler["findings"]) == 1


def test_source_is_not_executed_and_empty_file_has_no_invented_handlers() -> None:
    source = "raise RuntimeError('never execute')\n" + handler_source("return []")
    assert inspect(source)["handlers"][0]["findings"]
    result = inspect("")
    assert result["state"] == "analyzed" and result["handlers"] == []


def test_parse_failure_retains_error_path_and_source_hash_without_handlers() -> None:
    source = "def invalid(:\n"
    result = inspect(source)
    assert result["state"] == "failed"
    assert result["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert result["diagnostic"]["severity"] == "error"
    assert result["diagnostic"]["path"] == "errors.py"
    assert "handlers" not in result
