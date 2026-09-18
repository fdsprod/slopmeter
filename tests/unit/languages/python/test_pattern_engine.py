"""Independent fake-rule contracts for deterministic pattern execution."""

import ast
from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import (
    AnalyzedPatterns,
    FailedPatterns,
    FileEvidence,
    PatternFinding,
)
from slop_measure.domain.source import ProjectPath
from slop_measure.errors import InvalidRuleSelection
from slop_measure.languages.python.patterns import (
    PythonParsedUnit,
    PythonPatternRule,
    PythonProjectContext,
    RuleMetadata,
    run_patterns,
    select_rules,
)


def unit() -> PythonParsedUnit:
    source = "a = True\nb = False\nc = True\n"
    file = FileEvidence.model_validate(
        {
            "path": "app.py",
            "language": "python",
            "cohort": "production",
            "sloc": 3,
            "sloc_lines": (1, 2, 3),
            "parse_state": "parsed",
        }
    )
    return PythonParsedUnit(tree=ast.parse(source), file=file, source=source)


def metadata(rule_id: str = "example") -> RuleMetadata:
    return RuleMetadata.model_validate(
        {"rule_id": rule_id, "category": "redundancy", "message": "Redundant source."}
    )


def finding(rule_id: str = "example", start: int = 1, **changes: object) -> PatternFinding:
    return PatternFinding.model_validate(
        {
            "path": "app.py",
            "rule_id": rule_id,
            "category": "redundancy",
            "severity": "warning",
            "message": "Redundant source.",
            "span": {"start_line": start, "end_line": start},
            **changes,
        }
    )


@dataclass(frozen=True)
class FakeRule:
    metadata: RuleMetadata
    findings: tuple[PatternFinding, ...] = ()
    fail: bool = False

    def analyze(
        self, unit: PythonParsedUnit, context: PythonProjectContext
    ) -> tuple[PatternFinding, ...]:
        if self.fail:
            raise RuntimeError("fixture rule failure")
        return self.findings


def test_frozen_rule_satisfies_protocol_and_metadata_is_validated() -> None:
    rule: PythonPatternRule = FakeRule(metadata())
    assert rule.metadata.severity.value == "warning"
    assert rule.metadata.remediation is None
    assert rule.analyze(unit(), PythonProjectContext()) == ()
    with pytest.raises(ValidationError):
        rule.metadata.rule_id = "other"
    with pytest.raises(ValidationError):
        RuleMetadata.model_validate({**metadata().model_dump(), "unexpected": True})


@pytest.mark.parametrize("field", ["rule_id", "message", "remediation"])
def test_metadata_text_is_trimmed_nonempty(field: str) -> None:
    with pytest.raises(ValidationError):
        RuleMetadata.model_validate({**metadata().model_dump(), field: " "})
    assert (
        getattr(RuleMetadata.model_validate({**metadata().model_dump(), field: " text "}), field)
        == "text"
    )


def test_selection_sorts_ids_and_combines_allowlist_with_disabled_rules() -> None:
    a, b, c = (FakeRule(metadata(name)) for name in ("a", "b", "c"))
    rules = (c, b, a)
    assert select_rules(rules, AnalysisConfig()) == (a, b, c)
    assert select_rules(rules, AnalysisConfig(enabled_rules=frozenset({"a", "c"}))) == (a, c)
    assert select_rules(rules, AnalysisConfig(disabled_rules=frozenset({"b"}))) == (a, c)


def test_duplicate_rule_ids_fail_before_running_rules() -> None:
    with pytest.raises(ValueError):
        select_rules((FakeRule(metadata()), FakeRule(metadata())), AnalysisConfig())


@pytest.mark.parametrize("field", ["enabled_rules", "disabled_rules"])
def test_unknown_rule_selection_propagates_as_configuration_error(field: str) -> None:
    config = AnalysisConfig.model_validate({field: ["unknown"]})
    rules = (FakeRule(metadata(), fail=True),)
    with pytest.raises(InvalidRuleSelection):
        select_rules(rules, config)
    with pytest.raises(InvalidRuleSelection):
        run_patterns(unit(), PythonProjectContext(), config, rules=rules)


def test_pattern_runner_sorts_findings_and_deduplicates_identical_rule_spans() -> None:
    a = FakeRule(metadata("a"), (finding("a", 3), finding("a", 1), finding("a", 1)))
    b = FakeRule(metadata("b"), (finding("b", 1),))
    result = run_patterns(unit(), PythonProjectContext(), AnalysisConfig(), rules=(b, a))
    assert isinstance(result, AnalyzedPatterns)
    assert [(item.span.start_line, item.rule_id) for item in result.findings] == [
        (1, "a"),
        (1, "b"),
        (3, "a"),
    ]


@pytest.mark.parametrize(
    "change", ["path", "rule_id", "category", "severity", "span", "conflict", "exception"]
)
def test_invalid_rule_output_fails_the_file_without_partial_findings(change: str) -> None:
    changes = {
        "path": "other.py",
        "rule_id": "other",
        "category": "control-flow",
        "severity": "info",
        "span": {"start_line": 4, "end_line": 4},
    }
    bad = finding(**{change: changes[change]}) if change in changes else finding()
    findings = (bad, finding(message="Conflicting message.")) if change == "conflict" else (bad,)
    rules = (
        FakeRule(metadata("good"), (finding("good"),)),
        FakeRule(metadata(), findings, fail=change == "exception"),
    )
    result = run_patterns(unit(), PythonProjectContext(), AnalysisConfig(), rules=rules)
    assert isinstance(result, FailedPatterns)
    assert result.path == ProjectPath("app.py")
    assert result.diagnostic.code == "python.pattern-error"
    assert result.diagnostic.severity.value == "error"
    assert result.diagnostic.path == result.path


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_pattern_span_cannot_include_phantom_line_after_final_newline(newline: str) -> None:
    source = "value = 1" + newline
    file = FileEvidence.model_validate(
        {
            "path": "app.py",
            "language": "python",
            "cohort": "production",
            "sloc": 1,
            "sloc_lines": (1,),
            "parse_state": "parsed",
        }
    )
    parsed = PythonParsedUnit(tree=ast.parse(source), file=file, source=source)
    invalid = finding(span={"start_line": 1, "end_line": 2})
    result = run_patterns(
        parsed, PythonProjectContext(), AnalysisConfig(), rules=(FakeRule(metadata(), (invalid,)),)
    )

    assert isinstance(result, FailedPatterns)
    assert result.diagnostic.code == "python.pattern-error"


@pytest.mark.parametrize("expression", ['f"{value:>10}"', 'f"{value!r:>10}"'])
def test_literal_format_spec_is_not_a_standalone_literal_fstring(expression: str) -> None:
    source = f"result = {expression}\n"
    evidence = FileEvidence.model_validate(
        {
            "path": "app.py",
            "language": "python",
            "cohort": "production",
            "sloc": 1,
            "sloc_lines": (1,),
            "parse_state": "parsed",
        }
    )
    parsed = PythonParsedUnit(tree=ast.parse(source), file=evidence, source=source)
    config = AnalysisConfig(enabled_rules=frozenset({"py.literal-fstring"}))

    result = run_patterns(parsed, PythonProjectContext(), config)

    assert isinstance(result, AnalyzedPatterns)
    assert result.findings == ()


def run_catalog_source(source: str, rule_id: str) -> AnalyzedPatterns:
    lines = tuple(range(1, len(source.splitlines()) + 1))
    evidence = FileEvidence.model_validate(
        {
            "path": "app.py",
            "language": "python",
            "cohort": "production",
            "sloc": len(lines),
            "sloc_lines": lines,
            "parse_state": "parsed",
        }
    )
    parsed = PythonParsedUnit(tree=ast.parse(source), file=evidence, source=source)
    result = run_patterns(
        parsed, PythonProjectContext(), AnalysisConfig(enabled_rules=frozenset({rule_id}))
    )
    assert isinstance(result, AnalyzedPatterns)
    return result


@pytest.mark.parametrize("parameter", ["list", "*list", "**list"])
def test_type_parameters_prevent_builtin_constructor_assumptions(parameter: str) -> None:
    source = f"def f[{parameter}]():\n    return list([1])\n"
    assert run_catalog_source(source, "py.redundant-literal-container").findings == ()


@pytest.mark.parametrize(
    "following",
    [
        "    for item in items:\n        _relay(item)\n",
        "    if items:\n        _relay(items)\n",
        "    return consume(_relay(items))\n",
    ],
)
def test_trivial_wrapper_requires_a_direct_immediately_following_call(following: str) -> None:
    source = "def outer(items):\n    def _relay(item):\n        return target(item)\n" + following
    assert run_catalog_source(source, "py.trivial-wrapper").findings == ()


@pytest.mark.parametrize(
    "source,lines",
    [
        (
            "def outer(value):\n"
            "    def _relay(item):\n"
            "        # type: (int) -> int\n"
            "        return target(item)\n"
            "    return _relay(value)\n",
            (1, 2, 4, 5),
        ),
        (
            "def outer(value):\n"
            "    def _relay(item):  # type: (int) -> int\n"
            "        return target(item)\n"
            "    return _relay(value)\n",
            (1, 2, 3, 4),
        ),
    ],
)
def test_trivial_wrapper_preserves_pep484_type_comments(
    source: str, lines: tuple[int, ...]
) -> None:
    evidence = FileEvidence.model_validate(
        {
            "path": "app.py",
            "language": "python",
            "cohort": "production",
            "sloc": len(lines),
            "sloc_lines": lines,
            "parse_state": "parsed",
        }
    )
    parsed = PythonParsedUnit(tree=ast.parse(source), file=evidence, source=source)
    result = run_patterns(
        parsed,
        PythonProjectContext(),
        AnalysisConfig(enabled_rules=frozenset({"py.trivial-wrapper"})),
    )

    assert isinstance(result, AnalyzedPatterns)
    assert result.findings == ()


def test_single_use_return_binding_preserves_assignment_type_comment() -> None:
    source = "def f(value):\n    result = value  # type: int\n    return result\n"
    assert run_catalog_source(source, "py.single-use-return-binding").findings == ()
