"""Independent positive and keep-case contracts for the first pattern catalog."""

import ast
from textwrap import indent

import pytest

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import AnalyzedPatterns, FileEvidence, PatternFinding
from slop_measure.domain.source import ProjectPath
from slop_measure.languages.python.patterns import (
    PythonParsedUnit,
    PythonProjectContext,
    run_patterns,
)
from slop_measure.languages.python.rules import RULE_SET_VERSION, RULES
from slop_measure.languages.python.sloc import classify_sloc

_CASES = (
    (
        "boolean-conditional",
        "value = True if check() else False\n",
        (1, 1),
        "value = 1 if check() else 0\n",
    ),
    (
        "negated-boolean-conditional",
        "value = False if check() else True\n",
        (1, 1),
        "value = False if check() else other\n",
    ),
    ("literal-fstring", 'value = f"hello"\n', (1, 1), 'value = f"hello {name}"\n'),
    (
        "literal-identity-comprehension",
        "value = [x for x in (1, 2)]\n",
        (1, 1),
        "value = [x for x in (1, 2) if x]\n",
    ),
    ("redundant-literal-container", "value = list([1, 2])\n", (1, 1), "value = list(source)\n"),
    (
        "redundant-else-after-return",
        "def f(flag):\n    if flag:\n        return 1\n    else:\n        return 2\n",
        (4, 4),
        "def f(a, b):\n    if a:\n        if b: return 1\n    else:\n        return 2\n",
    ),
    (
        "redundant-else-after-raise",
        "if flag:\n    raise Error\nelse:\n    work()\n",
        (3, 3),
        "if flag:\n    work()\nelse:\n    recover()\n",
    ),
    (
        "redundant-else-after-break",
        "for x in items:\n    if x:\n        break\n    else:\n        work()\n",
        (4, 4),
        "for x in items:\n    if x:\n        for y in others: break\n    else:\n        work()\n",
    ),
    (
        "redundant-else-after-continue",
        "for x in items:\n    if x:\n        continue\n    else:\n        work()\n",
        (4, 4),
        "for x in items:\n    if x:\n        work()\n    else:\n        continue\n",
    ),
    (
        "merge-nested-if",
        "if first:\n    if second:\n        work()\n",
        (2, 2),
        "if first:\n    work()\n    if second:\n        work()\n",
    ),
    (
        "redundant-except-reraise",
        "try:\n    work()\nexcept:\n    raise\n",
        (3, 4),
        "try:\n    work()\nexcept Error:\n    raise\n",
    ),
    (
        "empty-finally",
        "try:\n    work()\nfinally:\n    pass\n",
        (3, 4),
        "try:\n    work()\nfinally:\n    cleanup()\n",
    ),
    (
        "redundant-none-fallback",
        "def f(value):\n    return value if value is not None else None\n",
        (2, 2),
        "def f(value):\n    return value if value is not None else 0\n",
    ),
    (
        "redundant-dict-get-default",
        'value = {"a": 1}.get("a", None)\n',
        (1, 1),
        'value = mapping.get("a", None)\n',
    ),
    (
        "redundant-literal-none-guard",
        "def f():\n    value = 1\n    if value is None:\n        raise Error\n",
        (3, 3),
        "def f():\n    value = load()\n    if value is None:\n        raise Error\n",
    ),
    (
        "redundant-pass",
        "class C:\n    pass\n    value = 1\n",
        (2, 2),
        'class C:\n    "Docs"\n    pass\n',
    ),
    (
        "explicit-object-base",
        "class C(object):\n    pass\n",
        (1, 1),
        "class C(object, Other):\n    pass\n",
    ),
    (
        "explicit-default-metaclass",
        "class C(metaclass=type):\n    pass\n",
        (1, 1),
        "class C(Base, metaclass=type):\n    pass\n",
    ),
    (
        "trivial-wrapper",
        "def outer(value):\n    def _relay(item):\n"
        "        return target(item)\n    return _relay(value)\n",
        (2, 3),
        "def outer(value):\n    def relay(item):\n"
        "        return target(item)\n    return relay(value)\n",
    ),
    (
        "single-use-return-binding",
        "def f():\n    temporary = work()\n    return temporary\n",
        (2, 2),
        "def f():\n    temporary = work()\n    inspect(temporary)\n    return temporary\n",
    ),
)


def analyze(rule_id: str, source: str) -> tuple[PatternFinding, ...]:
    tree = ast.parse(source)
    lines = classify_sloc(source, tree)
    file = FileEvidence.model_validate(
        {
            "path": "app.py",
            "language": "python",
            "cohort": "production",
            "sloc": len(lines),
            "sloc_lines": lines,
            "parse_state": "parsed",
        }
    )
    selected = tuple(rule for rule in RULES if rule.metadata.rule_id == f"py.{rule_id}")
    assert len(selected) == 1
    result = run_patterns(
        PythonParsedUnit(tree=tree, file=file, source=source),
        PythonProjectContext(paths=(ProjectPath("app.py"),)),
        AnalysisConfig(),
        rules=selected,
    )
    assert isinstance(result, AnalyzedPatterns)
    return result.findings


def test_catalog_contains_exactly_twenty_sorted_rules_and_five_per_family() -> None:
    expected = {f"py.{case[0]}" for case in _CASES}
    ids = tuple(rule.metadata.rule_id for rule in RULES)
    assert set(ids) == expected
    assert len(ids) == 20
    assert ids == tuple(sorted(ids))
    assert RULE_SET_VERSION == "py-patterns-1"
    for category in ("redundancy", "control-flow", "defensive", "abstraction"):
        assert sum(rule.metadata.category.value == category for rule in RULES) == 5


@pytest.mark.parametrize("rule_id,source,span,keep", _CASES, ids=[case[0] for case in _CASES])
def test_each_rule_has_a_precise_positive_and_a_keep_case(
    rule_id: str, source: str, span: tuple[int, int], keep: str
) -> None:
    findings = analyze(rule_id, source)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == f"py.{rule_id}"
    assert finding.path == ProjectPath("app.py")
    assert (finding.span.start_line, finding.span.end_line) == span
    assert finding.message
    assert analyze(rule_id, keep) == ()


@pytest.mark.parametrize(
    "source",
    [
        "list = factory\nvalue = list([1])\n",
        "value = list([1])\nlist = factory\n",
        "def f(list):\n    return list([1])\n",
        "from custom import list\nvalue = list([1])\n",
        "from custom import *\nvalue = list([1])\n",
        "exec(source)\nvalue = list([1])\n",
        "def outer():\n    list = factory\n    def inner():\n        return list([1])\n",
        "class C:\n    list = factory\n    value = list([1])\n",
        "try:\n    work()\nexcept Error as list:\n    value = list([1])\n",
        "def f(value):\n    match value:\n        case {'factory': list}:\n"
        "            return list([1])\n",
    ],
)
def test_container_rule_keeps_shadowed_or_uncertain_builtin_calls(source: str) -> None:
    assert analyze("redundant-literal-container", source) == ()


@pytest.mark.parametrize(
    "rule_id,source",
    [
        ("explicit-object-base", "object = Base\nclass C(object): pass\n"),
        ("explicit-object-base", "@decorate\nclass C(object): pass\n"),
        ("explicit-object-base", "class C(object, metaclass=Meta): pass\n"),
        ("explicit-default-metaclass", "type = Meta\nclass C(metaclass=type): pass\n"),
        ("explicit-default-metaclass", "@decorate\nclass C(metaclass=type): pass\n"),
        ("explicit-default-metaclass", "class C(metaclass=type, flag=True): pass\n"),
        ("literal-identity-comprehension", "value = [x for x in source]\n"),
        ("literal-identity-comprehension", "value = [x for x in (*source,)]\n"),
        ("literal-identity-comprehension", "value = [x for x, y in ((1, 2),)]\n"),
        ("literal-identity-comprehension", "value = [x for x in (1,) for y in (2,)]\n"),
        ("literal-identity-comprehension", "async def f():\n    return [x async for x in (1,)]\n"),
        ("redundant-literal-container", "value = list((1, 2))\n"),
        ("redundant-literal-container", "value = dict({'x': 1}, y=2)\n"),
        ("merge-nested-if", "if a:\n    if b: work()\n    else: other()\n"),
        ("merge-nested-if", "if a:\n    if b: work()\nelse: other()\n"),
        ("redundant-except-reraise", "try: work()\nexcept:\n    log()\n    raise\n"),
        ("redundant-except-reraise", "try: work()\nexcept: raise\nfinally: cleanup()\n"),
        ("redundant-except-reraise", "try: work()\nexcept: raise Error from cause\n"),
        ("empty-finally", "try: work()\nfinally:\n    pass\n    cleanup()\n"),
        ("redundant-dict-get-default", "value = {}.get('a', 0)\n"),
        ("redundant-dict-get-default", "value = {}.get(*args)\n"),
        ("redundant-pass", "def f():\n    pass\n"),
        ("redundant-pass", "def f():\n    ...\n    pass\n"),
        ("redundant-pass", "if flag:\n    pass\n"),
    ],
)
def test_rules_keep_nonmatching_and_intentional_forms(rule_id: str, source: str) -> None:
    assert analyze(rule_id, source) == ()


@pytest.mark.parametrize(
    "rule_id,source",
    [
        ("redundant-none-fallback", "value = x if x is not None else None\n"),
        (
            "redundant-none-fallback",
            "def f():\n    global x\n    return x if x is not None else None\n",
        ),
        (
            "redundant-none-fallback",
            "def outer(x):\n    def inner():\n        return x if x is not None else None\n",
        ),
        (
            "redundant-none-fallback",
            "def f(obj):\n    return obj.x if obj.x is not None else None\n",
        ),
        (
            "redundant-none-fallback",
            "def f():\n    return call() if call() is not None else None\n",
        ),
        (
            "redundant-none-fallback",
            "def f(x):\n    locals()\n    return x if x is not None else None\n",
        ),
        (
            "redundant-literal-none-guard",
            "def f():\n    global value\n    value = 1\n    if value is None: raise Error\n",
        ),
        (
            "redundant-literal-none-guard",
            "def f():\n    value = None\n    if value is None: raise Error\n",
        ),
        (
            "redundant-literal-none-guard",
            "def f():\n    value: int = 1\n    if value is None: raise Error\n",
        ),
        (
            "redundant-literal-none-guard",
            "def f():\n    value = 1\n    work()\n    if value is None: raise Error\n",
        ),
        ("single-use-return-binding", "def f():\n    global x\n    x = work()\n    return x\n"),
        (
            "single-use-return-binding",
            "def outer(x):\n    def inner():\n        nonlocal x\n"
            "        x = work()\n        return x\n",
        ),
        (
            "single-use-return-binding",
            "def f():\n    def capture(): return x\n    x = work()\n    return x\n",
        ),
        ("single-use-return-binding", "def f():\n    x: int = work()\n    return x\n"),
        ("single-use-return-binding", "def f():\n    locals()\n    x = work()\n    return x\n"),
        ("single-use-return-binding", "async def f():\n    x = await work()\n    return x\n"),
        ("single-use-return-binding", "def f():\n    x = yield 1\n    return x\n"),
    ],
)
def test_name_based_rules_require_stable_local_bindings(rule_id: str, source: str) -> None:
    assert analyze(rule_id, source) == ()


@pytest.mark.parametrize(
    "body",
    [
        "@decorate\ndef _relay(item):\n    return target(item)\nreturn _relay(value)\n",
        "def _relay(item: int):\n    return target(item)\nreturn _relay(value)\n",
        "def _relay(item) -> int:\n    return target(item)\nreturn _relay(value)\n",
        "def _relay(item=1):\n    return target(item)\nreturn _relay(value)\n",
        "async def _relay(item):\n    return target(item)\nreturn _relay(value)\n",
        "def _relay(item):\n    yield target(item)\nreturn _relay(value)\n",
        "def _relay(item):\n    return target(item)\nreturn register(_relay)\n",
        "def _relay(item):\n    return target(item)\n_relay(value)\nreturn _relay(value)\n",
        "def _relay(item):\n    return target(item)\n_relay = replacement\nreturn _relay(value)\n",
        "def _relay(item):\n    'Purpose'\n    return target(item)\nreturn _relay(value)\n",
        "def _relay(*items):\n    return target(*items)\nreturn _relay(value)\n",
        "def _relay(item):\n    return target(item=item)\nreturn _relay(value)\n",
        "def _relay(item):\n    return _relay(item)\nreturn _relay(value)\n",
        "def _relay(item):\n    return target(item + 1)\nreturn _relay(value)\n",
        "locals()\ndef _relay(item):\n    return target(item)\nreturn _relay(value)\n",
    ],
)
def test_wrapper_rule_preserves_api_features_callbacks_and_additional_uses(body: str) -> None:
    assert analyze("trivial-wrapper", "def outer(value):\n" + indent(body, "    ")) == ()


@pytest.mark.parametrize(
    "source",
    [
        "def _relay(item):\n    return target(item)\nvalue = _relay(1)\n",
        "class C:\n    def _relay(self, item):\n        return target(item)\n",
    ],
)
def test_wrapper_rule_does_not_infer_external_visibility(source: str) -> None:
    assert analyze("trivial-wrapper", source) == ()


@pytest.mark.parametrize(
    "rule_id,source,span",
    [
        (
            "redundant-else-after-return",
            "def f(flag):\n    if flag:\n        return 1\n"
            "    # keep the comment\n\n    else:\n        return 2\n",
            (6, 6),
        ),
        ("merge-nested-if", "if a:\n    if (\n        b\n    ):\n        work()\n", (2, 4)),
        (
            "redundant-except-reraise",
            "try:\n    work()\n# note\nexcept:\n    # note\n    raise\n",
            (4, 6),
        ),
        ("empty-finally", "try:\n    work()\n# note\nfinally:\n    # note\n    pass\n", (4, 6)),
        ("boolean-conditional", "value = (\n    True\n    if check()\n    else False\n)\n", (2, 4)),
        ("explicit-object-base", "class C(\n    object\n):\n    pass\n", (2, 2)),
        ("explicit-default-metaclass", "class C(\n    metaclass=type\n):\n    pass\n", (2, 2)),
    ],
)
def test_finding_spans_follow_tokens_and_ast_not_neighbor_line_guesses(
    rule_id: str, source: str, span: tuple[int, int]
) -> None:
    findings = analyze(rule_id, source)
    assert len(findings) == 1
    assert (findings[0].span.start_line, findings[0].span.end_line) == span
