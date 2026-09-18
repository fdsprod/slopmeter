"""Behavioral tests for language-neutral analyzer evidence contracts."""

import pytest
from pydantic import ValidationError

from slop_measure.domain.evidence import (
    Coverage,
    CoverageState,
    Diagnostic,
    DiagnosticSeverity,
    EvidenceCapability,
    FileEvidence,
    LanguageEvidence,
    ParseState,
    SourceSpan,
)
from slop_measure.domain.source import Cohort, ProjectPath


def parsed_file(
    path: str = "src/app.py",
    *,
    sloc_lines: tuple[int, ...] = (1, 3, 4),
) -> FileEvidence:
    """Build one valid file record for focused validation tests."""
    return FileEvidence(
        path=ProjectPath(path),
        language="python",
        cohort=Cohort.PRODUCTION,
        sloc=len(sloc_lines),
        sloc_lines=sloc_lines,
        parse_state=ParseState.PARSED,
    )


@pytest.mark.parametrize("value", ["info", "warning", "error"])
def test_diagnostic_severity_is_closed(value: str) -> None:
    assert DiagnosticSeverity(value).value == value


def test_diagnostic_severity_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        DiagnosticSeverity("fatal")


def test_diagnostic_has_stable_text_and_optional_source_location() -> None:
    diagnostic = Diagnostic(
        severity=DiagnosticSeverity.ERROR,
        code="python.parse-error",
        message="Python source could not be parsed.",
        path=ProjectPath("src/broken.py"),
        span=SourceSpan(start_line=7, end_line=9),
    )

    assert diagnostic.model_dump(mode="json") == {
        "severity": "error",
        "code": "python.parse-error",
        "message": "Python source could not be parsed.",
        "path": "src/broken.py",
        "span": {"start_line": 7, "end_line": 9},
    }

    project_diagnostic = Diagnostic(
        severity=DiagnosticSeverity.WARNING,
        code="python.unavailable",
        message="Python analysis is unavailable.",
    )
    assert project_diagnostic.path is None
    assert project_diagnostic.span is None


@pytest.mark.parametrize("field", ["code", "message"])
def test_diagnostic_requires_nonempty_stable_text(field: str) -> None:
    values = {
        "severity": DiagnosticSeverity.INFO,
        "code": "analysis.info",
        "message": "Analysis completed with a notice.",
    }
    values[field] = "   "

    with pytest.raises(ValidationError):
        Diagnostic.model_validate(values)


@pytest.mark.parametrize(
    ("start_line", "end_line"),
    [(0, 1), (1, 0), (-1, 3), (4, 3)],
)
def test_source_span_is_one_based_inclusive_and_ordered(
    start_line: int,
    end_line: int,
) -> None:
    with pytest.raises(ValidationError):
        SourceSpan(start_line=start_line, end_line=end_line)


def test_source_span_accepts_a_single_inclusive_line() -> None:
    assert SourceSpan(start_line=6, end_line=6).model_dump() == {
        "start_line": 6,
        "end_line": 6,
    }


@pytest.mark.parametrize("value", ["scored", "excluded", "unsupported"])
def test_coverage_state_distinguishes_inventory_outcomes(value: str) -> None:
    assert CoverageState(value).value == value


def test_coverage_carries_scope_counts_and_an_optional_reason() -> None:
    scored = Coverage(
        state=CoverageState.SCORED,
        cohort=Cohort.PRODUCTION,
        language="python",
        file_count=2,
        sloc=8,
    )
    excluded = Coverage(
        state=CoverageState.EXCLUDED,
        cohort=Cohort.TEST,
        language="python",
        file_count=3,
        sloc=0,
        reason="configured exclusion",
    )

    assert scored.reason is None
    assert excluded.reason == "configured exclusion"
    assert excluded.model_dump(mode="json")["state"] == "excluded"


@pytest.mark.parametrize(
    ("field", "value"),
    [("file_count", -1), ("sloc", -1)],
)
def test_coverage_rejects_negative_totals(field: str, value: int) -> None:
    values = {
        "state": CoverageState.SCORED,
        "cohort": Cohort.PRODUCTION,
        "language": "python",
        "file_count": 1,
        "sloc": 2,
    }
    values[field] = value

    with pytest.raises(ValidationError):
        Coverage.model_validate(values)


@pytest.mark.parametrize("value", ["parsed", "failed"])
def test_parse_state_is_closed(value: str) -> None:
    assert ParseState(value).value == value


def test_file_evidence_preserves_exact_sorted_unique_sloc_lines() -> None:
    evidence = parsed_file(sloc_lines=(2, 5, 8))

    assert evidence.path == ProjectPath("src/app.py")
    assert evidence.language == "python"
    assert evidence.cohort is Cohort.PRODUCTION
    assert evidence.sloc == 3
    assert evidence.sloc_lines == (2, 5, 8)
    assert evidence.parse_state is ParseState.PARSED


@pytest.mark.parametrize(
    "sloc_lines",
    [(), (0,), (-1, 2), (2, 1), (1, 1)],
)
def test_file_evidence_rejects_invalid_sloc_line_sets(
    sloc_lines: tuple[int, ...],
) -> None:
    with pytest.raises(ValidationError):
        FileEvidence(
            path=ProjectPath("src/app.py"),
            language="python",
            cohort=Cohort.PRODUCTION,
            sloc=max(1, len(sloc_lines)),
            sloc_lines=sloc_lines,
            parse_state=ParseState.PARSED,
        )


def test_file_evidence_requires_sloc_count_to_match_exact_lines() -> None:
    with pytest.raises(ValidationError):
        FileEvidence(
            path=ProjectPath("src/app.py"),
            language="python",
            cohort=Cohort.PRODUCTION,
            sloc=4,
            sloc_lines=(1, 3, 5),
            parse_state=ParseState.PARSED,
        )


def test_failed_file_can_have_no_source_lines() -> None:
    evidence = FileEvidence(
        path=ProjectPath("src/broken.py"),
        language="python",
        cohort=Cohort.PRODUCTION,
        sloc=0,
        sloc_lines=(),
        parse_state=ParseState.FAILED,
    )

    assert evidence.sloc_lines == ()
    assert evidence.sloc == 0


def test_evidence_capabilities_are_closed() -> None:
    assert {capability.value for capability in EvidenceCapability} == {
        "files",
        "patterns",
        "functions",
        "clones",
    }

    with pytest.raises(ValueError):
        EvidenceCapability("types")


def test_language_evidence_has_immutable_language_neutral_defaults() -> None:
    file = parsed_file()
    evidence = LanguageEvidence(
        language="python",
        capabilities=frozenset({EvidenceCapability.FILES}),
        files=(file,),
    )

    assert evidence.language == "python"
    assert evidence.capabilities == frozenset({EvidenceCapability.FILES})
    assert evidence.files == (file,)
    assert evidence.patterns == ()
    assert evidence.functions == ()
    assert evidence.clone_candidates == ()
    assert evidence.diagnostics == ()
    assert evidence.model_dump(mode="json") == {
        "language": "python",
        "capabilities": ["files"],
        "files": [file.model_dump(mode="json")],
        "patterns": [],
        "functions": [],
        "clone_candidates": [],
        "diagnostics": [],
    }


def test_language_evidence_rejects_duplicate_file_paths() -> None:
    with pytest.raises(ValidationError):
        LanguageEvidence(
            language="python",
            capabilities=frozenset({EvidenceCapability.FILES}),
            files=(parsed_file(), parsed_file()),
        )


def test_language_evidence_rejects_files_from_another_language() -> None:
    with pytest.raises(ValidationError):
        LanguageEvidence(
            language="typescript",
            capabilities=frozenset({EvidenceCapability.FILES}),
            files=(parsed_file(),),
        )


def test_diagnostic_span_requires_a_source_path() -> None:
    with pytest.raises(ValidationError):
        Diagnostic(
            severity=DiagnosticSeverity.ERROR,
            code="python.parse-error",
            message="Python source could not be parsed.",
            span=SourceSpan(start_line=1, end_line=2),
        )


def test_capabilities_have_deterministic_json_order() -> None:
    evidence = LanguageEvidence(
        language="python",
        capabilities=frozenset(EvidenceCapability),
        files=(),
    )

    assert evidence.model_dump(mode="json")["capabilities"] == [
        "clones",
        "files",
        "functions",
        "patterns",
    ]


@pytest.mark.parametrize(
    "model",
    [
        SourceSpan(start_line=1, end_line=1),
        Diagnostic(
            severity=DiagnosticSeverity.INFO,
            code="analysis.info",
            message="Analysis completed with a notice.",
        ),
        Coverage(
            state=CoverageState.SCORED,
            cohort=Cohort.PRODUCTION,
            language="python",
            file_count=1,
            sloc=3,
        ),
        parsed_file(),
        LanguageEvidence(
            language="python",
            capabilities=frozenset({EvidenceCapability.FILES}),
            files=(parsed_file(),),
        ),
    ],
)
def test_evidence_contracts_are_immutable(model: object) -> None:
    with pytest.raises(ValidationError):
        model.language = "typescript"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("model_type", "values"),
    [
        (SourceSpan, {"start_line": 1, "end_line": 1}),
        (
            Diagnostic,
            {
                "severity": "info",
                "code": "analysis.info",
                "message": "Analysis completed with a notice.",
            },
        ),
        (
            Coverage,
            {
                "state": "scored",
                "cohort": "production",
                "language": "python",
                "file_count": 1,
                "sloc": 1,
            },
        ),
        (
            FileEvidence,
            {
                "path": "src/app.py",
                "language": "python",
                "cohort": "production",
                "sloc": 1,
                "sloc_lines": (1,),
                "parse_state": "parsed",
            },
        ),
        (
            LanguageEvidence,
            {
                "language": "python",
                "capabilities": frozenset({"files"}),
                "files": (),
            },
        ),
    ],
)
def test_evidence_contracts_forbid_extra_fields(
    model_type: type[object],
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model_type.model_validate({**values, "parser_node": object()})  # type: ignore[attr-defined]
