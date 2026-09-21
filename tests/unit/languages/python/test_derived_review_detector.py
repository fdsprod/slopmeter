"""Only proved straight-line local-list evidence becomes a review candidate."""

import hashlib

import pytest

from slop_measure.domain.source import Cohort, ProjectPath, SourceDocument
from slop_measure.languages.python.derived_review import analyze_derived


def inspect(source: str) -> dict:
    return analyze_derived(
        SourceDocument(
            path=ProjectPath("derived.py"),
            language="python",
            cohort=Cohort.PRODUCTION,
            content=source.encode(),
        )
    ).model_dump(mode="json")


def function(body: str, *, parameters: str = "") -> str:
    return f"def work({parameters}):\n" + "".join(f"    {line}\n" for line in body.splitlines())


@pytest.mark.parametrize(
    "mutation,kind",
    [
        ("items.append(3)", "append"),
        ("items.extend([3, 4])", "extend"),
        ("items.insert(0, 3)", "insert"),
    ],
)
@pytest.mark.parametrize("read", ["return count", "value = count"])
def test_stale_count_retains_exact_derivation_mutation_and_read(
    mutation: str, kind: str, read: str
) -> None:
    source = function(f"items = [1, 2]\ncount = len(items)\n{mutation}\n{read}")
    result = inspect(source)
    assert result["state"] == "analyzed" and result["path"] == "derived.py"
    assert result["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    (scope,) = result["functions"]
    assert scope["state"] == "analyzed" and scope["symbol"] == "work"
    assert scope["span"] == dict(start_line=1, end_line=5)
    assert scope["findings"] == [
        dict(
            kind="stale-derived-state",
            derived_name="count",
            source_name="items",
            mutation_kind=kind,
            derivation=dict(start_line=3, end_line=3),
            mutation=dict(start_line=4, end_line=4),
            read=dict(start_line=5, end_line=5),
        )
    ]


@pytest.mark.parametrize(
    "body",
    [
        "items = [1]\ncount = len(items)\nitems.append(2)\ncount = len(items)\nreturn count",
        "items = [1]\ncount = len(items)\nreturn count",
        "items = [1]\ncount = len(items)\nitems.append(2)\nreturn 0",
        "items = [1]\ncount = len(items)\nitems.extend([])\nreturn count",
        "items = [1]\ncount = len(items)\nitems.append(2)\ncount = 0\nreturn count",
    ],
)
def test_recomputed_unmutated_or_unread_counts_have_no_stale_evidence(body: str) -> None:
    scope = inspect(function(body))["functions"][0]
    assert scope["state"] == "analyzed" and scope["findings"] == []


@pytest.mark.parametrize(
    "body,parameters",
    [
        ("items = [1]\ncount = len(items)\nalias = items\nitems.append(2)\nreturn count", ""),
        ("items = [1]\ncount = len(items)\nif flag:\n    items.append(2)\nreturn count", "flag"),
        ("items = [1]\ncount = len(items)\nunknown(items)\nitems.append(2)\nreturn count", ""),
        ("items = [1]\ncount = len(items)\nitems.append(make_value())\nreturn count", ""),
        ("count = len(items)\nitems.append(2)\nreturn count", "items"),
        ("items = [1]\ncount = len(items)\nitems = [2, 3]\nreturn count", ""),
        ("items = [1]\ncount = len(items)\nitems.pop()\nreturn count", ""),
        ("items = [1]\ncount = len(items)\nitems.append(2)\nreturn count", "len"),
        ("global items\ncount = len(items)\nitems.append(2)\nreturn count", ""),
        (
            "items = [1]\nsnapshot = tuple(items)\ncount = len(snapshot)\n"
            "items.append(2)\nreturn count",
            "",
        ),
    ],
)
def test_uncertain_len_candidates_are_explicitly_unresolved(body: str, parameters: str) -> None:
    scope = inspect(function(body, parameters=parameters))["functions"][0]
    assert scope["state"] == "unresolved" and scope["reason"]
    assert "findings" not in scope


def test_module_binding_of_len_prevents_builtin_proof() -> None:
    source = "len = custom_len\n" + function(
        "items = [1]\ncount = len(items)\nitems.append(2)\nreturn count"
    )
    assert inspect(source)["functions"][0]["state"] == "unresolved"


def test_later_local_binding_of_len_prevents_builtin_proof() -> None:
    source = function(
        "items = [1]\ncount = len(items)\nitems.append(2)\nvalue = count\nlen = custom_len"
    )
    assert inspect(source)["functions"][0]["state"] == "unresolved"


@pytest.mark.parametrize(
    "prefix,parameters",
    [
        ("try:\n    risky()\nexcept Exception as len:\n    pass\n", ""),
        ("", "unused=(len := custom_len)"),
        ("", "unused: (len := custom_len)"),
    ],
)
def test_indirect_module_bindings_prevent_builtin_len_proof(prefix: str, parameters: str) -> None:
    source = prefix + function(
        "items = [1]\ncount = len(items)\nitems.append(2)\nreturn count",
        parameters=parameters,
    )
    assert inspect(source)["functions"][0]["state"] == "unresolved"


@pytest.mark.parametrize(
    "prefix",
    [
        "match (lambda value: 42):\n    case len:\n        pass\n",
        "globals()['len'] = lambda value: 42\n",
        "__builtins__ = {'len': lambda value: 42}\n",
    ],
)
def test_dynamic_or_pattern_builtin_bindings_are_unresolved(prefix: str) -> None:
    source = prefix + function("items = [1]\ncount = len(items)\nitems.append(2)\nreturn count")
    assert inspect(source)["functions"][0]["state"] == "unresolved"


def test_type_parameter_shadowing_len_is_unresolved() -> None:
    source = function("items = [1]\ncount = len(items)\nitems.append(2)\nreturn count")
    source = source.replace("def work():", "def work[len]():")
    assert inspect(source)["functions"][0]["state"] == "unresolved"


def test_repeated_read_on_same_line_has_one_evidence_record() -> None:
    source = function("items = [1]\ncount = len(items)\nitems.append(2)\nreturn count, count")
    scope = inspect(source)["functions"][0]
    assert scope["state"] == "analyzed" and len(scope["findings"]) == 1


def test_nonlocal_candidate_remains_unresolved() -> None:
    source = (
        "def outer():\n    items = [1]\n    def inner():\n"
        "        nonlocal items\n        count = len(items)\n"
        "        items.append(2)\n        return count\n"
    )
    result = inspect(source)
    assert result["functions"]
    assert all(item["state"] == "unresolved" for item in result["functions"])


def test_source_is_never_executed_and_functions_are_independent() -> None:
    source = 'raise RuntimeError("never execute")\n' + function(
        "items = [1]\ncount = len(items)\nitems.append(2)\nreturn count"
    )
    result = inspect(source)
    assert result["functions"][0]["findings"]


def test_parse_failure_is_explicit_failed_file() -> None:
    result = inspect("def invalid(:\n")
    assert result["state"] == "failed"
    assert result["diagnostic"]["severity"] == "error"
    assert result["diagnostic"]["path"] == "derived.py"
