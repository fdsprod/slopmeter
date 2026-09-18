"""Immutable selections of existing report evidence."""

from pydantic import BaseModel, ConfigDict

from slop_measure.domain.evidence import FunctionEvidence
from slop_measure.domain.reports import ReportCloneGroup, ReportFinding, SourceSide
from slop_measure.domain.source import Cohort


class ErosionFinding(BaseModel):
    """One eroded callable with its source population."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    source: SourceSide
    language: str
    cohort: Cohort
    function: FunctionEvidence


class FindingSelection(BaseModel):
    """Native evidence families without fabricated shared rule or severity fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    patterns: tuple[ReportFinding, ...] = ()
    clone_groups: tuple[ReportCloneGroup, ...] = ()
    functions: tuple[ErosionFinding, ...] = ()
