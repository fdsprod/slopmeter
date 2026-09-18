"""Explain the versioned complexity basis without changing source evidence."""

from math import sqrt

from rich.console import Console

from slop_measure.domain.evidence import FunctionEvidence
from slop_measure.domain.source import Cohort


def effective_complexity(
    function: FunctionEvidence, cohort: Cohort, version: str | None
) -> int | None:
    if version not in {"1", "2", "3"}:
        return None
    return function.complexity_for(cohort) if version == "3" else function.cyclomatic_complexity


def render_callable_basis(
    console: Console,
    function: FunctionEvidence,
    cohort: Cohort,
    threshold: int,
    version: str | None,
) -> None:
    effective = effective_complexity(function, cohort, version)
    if effective is None:
        console.print("    M4 basis unavailable: unknown metric version")
        return
    basis = "full-cc"
    if version == "3" and cohort is Cohort.TEST:
        basis = (
            "assertion-excluded-cc"
            if function.assertion_count is not None
            else "full-cc (assertion count unavailable)"
        )
    mass = effective * sqrt(function.sloc)
    numerator = (
        (mass if effective > threshold else 0)
        if version == "1"
        else max(0, effective - threshold) * sqrt(function.sloc)
    )
    label = "above-threshold mass" if version == "1" else "excess mass"
    console.print(
        f"    M4 basis: {basis}; effective CC {effective}; effective mass {mass:g}; "
        f"{label} {numerator:g}; threshold > {threshold}"
    )
    if (
        cohort is Cohort.PRODUCTION
        and function.control_flow_complexity is not None
        and function.control_flow_complexity <= threshold < function.cyclomatic_complexity
    ):
        console.print(
            "    Classification review: assertions cause this production callable to exceed "
            "the threshold. Inspect whether it contains an embedded self-check. Production "
            "assertions can be real logic; classification and score are unchanged. Separate "
            "test scenarios or configure test paths only when ownership justifies it."
        )
