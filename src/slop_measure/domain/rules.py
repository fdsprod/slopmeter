"""Owned rule metadata shared by adapters and catalog views."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from slop_measure.domain.evidence import DiagnosticSeverity, PatternCategory

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RuleMetadata(BaseModel):
    """Stable identity and explanation for one source pattern."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: _Text
    category: PatternCategory
    severity: DiagnosticSeverity = DiagnosticSeverity.WARNING
    message: _Text
    remediation: _Text | None = None


class RuleEntry(BaseModel):
    """One catalog rule and its resolved selection state."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    metadata: RuleMetadata
    enabled: bool


class RuleCatalog(BaseModel):
    """Versioned metadata returned without analyzing source files."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    language: _Text
    version: _Text
    rules: tuple[RuleEntry, ...]
