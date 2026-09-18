"""Validated rule selection and deterministic per-file pattern analysis."""

import ast
import io
import tokenize
from dataclasses import dataclass
from functools import cached_property
from typing import Protocol

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import (
    AnalyzedPatterns,
    Diagnostic,
    DiagnosticSeverity,
    FailedPatterns,
    FileEvidence,
    PatternAnalysis,
    PatternFinding,
    pattern_source_lines,
)
from slop_measure.domain.rules import RuleMetadata
from slop_measure.domain.source import ProjectPath
from slop_measure.errors import InvalidRuleSelection

__all__ = ["RuleMetadata"]


@dataclass(frozen=True)
class PythonParsedUnit:
    """Adapter-private source and its existing parse and line evidence."""

    tree: ast.Module
    file: FileEvidence
    source: str

    @cached_property
    def token_stream(self) -> tuple[tokenize.TokenInfo, ...]:
        """Tokenize immutable source once, retaining tokens only with this unit."""
        source = self.source.replace("\r\n", "\n").replace("\r", "\n")
        return tuple(tokenize.generate_tokens(io.StringIO(source).readline))


@dataclass(frozen=True)
class PythonProjectContext:
    """Supplied document paths, without a claim of whole-project reachability."""

    paths: tuple[ProjectPath, ...] = ()


class PythonPatternRule(Protocol):
    """Inspect shared source facts without mutating them."""

    @property
    def metadata(self) -> RuleMetadata: ...

    def analyze(
        self, unit: PythonParsedUnit, context: PythonProjectContext
    ) -> tuple[PatternFinding, ...]: ...


def select_rules(
    rules: tuple[PythonPatternRule, ...], config: AnalysisConfig
) -> tuple[PythonPatternRule, ...]:
    """Validate IDs and return enabled rules in stable ID order."""
    by_id = {rule.metadata.rule_id: rule for rule in rules}
    if len(by_id) != len(rules):
        raise ValueError("pattern catalog cannot contain duplicate rule IDs")
    unknown = (config.enabled_rules | config.disabled_rules) - by_id.keys()
    if unknown:
        raise InvalidRuleSelection(f"Unknown pattern rules: {', '.join(sorted(unknown))}")
    selected = (config.enabled_rules or by_id.keys()) - config.disabled_rules
    return tuple(by_id[rule_id] for rule_id in sorted(selected))


def _validate_finding(
    finding: PatternFinding, metadata: RuleMetadata, unit: PythonParsedUnit
) -> None:
    if any(
        getattr(finding, field) != getattr(metadata, field)
        for field in ("rule_id", "category", "severity", "message", "remediation")
    ):
        raise ValueError("pattern finding must match its rule metadata")
    source = unit.source.replace("\r\n", "\n").replace("\r", "\n")
    line_count = source.count("\n") + bool(source and not source.endswith("\n"))
    if finding.span.end_line > line_count:
        raise ValueError("pattern span cannot extend beyond its source")
    pattern_source_lines(unit.file, finding)


def run_patterns(
    unit: PythonParsedUnit,
    context: PythonProjectContext,
    config: AnalysisConfig,
    *,
    rules: tuple[PythonPatternRule, ...] | None = None,
) -> PatternAnalysis:
    """Return complete file findings or an explicit file analysis failure."""
    if rules is None:
        # Import after the engine contract exists to avoid a catalog import cycle.
        from slop_measure.languages.python.rules import RULES  # noqa: PLC0415

        rules = RULES
    selected = select_rules(rules, config)
    try:
        findings: dict[tuple[int, int, str], PatternFinding] = {}
        for rule in selected:
            for finding in rule.analyze(unit, context):
                _validate_finding(finding, rule.metadata, unit)
                key = (finding.span.start_line, finding.span.end_line, finding.rule_id)
                if key in findings and findings[key] != finding:
                    raise ValueError("pattern finding identity has conflicting evidence")
                findings[key] = finding
        return AnalyzedPatterns(
            path=unit.file.path, findings=tuple(findings[key] for key in sorted(findings))
        )
    except Exception as error:
        return FailedPatterns(
            path=unit.file.path,
            diagnostic=Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="python.pattern-error",
                message=str(error) or "Python pattern analysis failed.",
                path=unit.file.path,
            ),
        )
