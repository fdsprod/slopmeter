"""Immutable discovery results before language analysis."""

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from slop_measure.domain.evidence import (
    Coverage,
    CoverageState,
    Diagnostic,
    FileEvidence,
    ParseState,
)
from slop_measure.domain.source import SourceDocument


class SourceInventory(BaseModel):
    """Readable documents, skipped coverage, and source-read failures."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    documents: tuple[SourceDocument, ...] = ()
    coverage: tuple[Coverage, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    failed_files: tuple[FileEvidence, ...] = ()

    @model_validator(mode="after")
    def validate_coverage(self) -> Self:
        if any(item.state is CoverageState.SCORED or item.sloc != 0 for item in self.coverage):
            raise ValueError("inventory coverage contains only unanalyzed skipped files")
        return self

    @model_validator(mode="after")
    def validate_source_outcomes(self) -> Self:
        paths = [item.path.root for item in (*self.documents, *self.failed_files)]
        if len(paths) != len(set(paths)):
            raise ValueError("each inventory path must have exactly one discovery outcome")
        if any(
            item.parse_state is not ParseState.FAILED or item.sloc for item in self.failed_files
        ):
            raise ValueError("failed inventory files require failed state and no source lines")
        return self
