"""Versioned interpretation policy, separate from a report's measured facts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReportInterpretation(BaseModel):
    """Shared guidance for human and agent review of current or historical reports."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["1.0"] = "1.0"
    purpose: str = (
        "Use this report to prioritize source review. A high score means inspect; "
        "it does not require a refactor."
    )
    score_meaning: str = (
        "Scores are calibrated relative to a reference corpus; lower is better. "
        "Points are neither percent bad code nor probability of a defect. "
        "Raw metric ratios and calibrated scores are different measurements."
    )
    metric_meanings: tuple[str, ...] = (
        "M1 measures source-line change, not quality. Growth alone is not a regression.",
        "M2 is the share of source lines matched by pattern rules. Matches are review "
        "suggestions, not proven defects.",
        "M3 is the share of source lines in detected clone groups. Duplication can be "
        "intentional; check whether shared behavior should actually change together.",
        "Combined verbosity is the union of M2 and M3 lines, not their sum. It avoids "
        "counting a line twice.",
        "Check metric versions in provenance. M4 version 2 is gradual excess complexity: "
        "sum(max(0, CC - threshold) * sqrt(SLOC)) / sum(CC * sqrt(SLOC)). "
        "Size weights the result; a single CC11 callable at threshold 10 measures 1/11. "
        "Legacy M4 version 1 is binary: all mass of each above-threshold callable counts.",
        "Project metrics combine their underlying totals, not an average of file scores. "
        "The score model and contribution weights are recorded with each scored result.",
        "A severity-weighted contribution is percentile * raw value * weight. The new "
        "py-2026.2 profile uses this for erosion so a small excess does not dominate just "
        "because it is uncommon. Individual metric percentiles remain reference ranks; "
        "they are not the adjusted contribution or the overall score.",
        "A rules catalog lists enabled checks; it is not evidence that source was scanned.",
    )
    limitations: tuple[str, ...] = (
        "Flat guards, predicates, and short readable functions can overstate refactoring "
        "need. Algorithm difficulty can understate it. Zero does not prove correctness.",
        "Check partial analysis, diagnostics, and excluded scope first. Unavailable is "
        "not zero. Compare scores only with compatible metric versions, profile, and config.",
        "Complexity does not measure intent, coupling, business risk, or the value of an "
        "extraction. Moving branches into helpers can lower a score without improving code.",
        "File rankings identify statistical hotspots, not a guaranteed order of useful "
        "fixes. A change in analyzed scope can change totals without a source-quality change.",
        "The gradual erosion formula was initially reviewed against nine examples in "
        "slop.measure. That is a provisional tuning baseline, not validation on all projects.",
    )
    review_steps: tuple[str, ...] = (
        "Read the source around each finding and its callers. Check the selected language, "
        "cohort, coverage, diagnostics, threshold, metric versions, and calibration profile.",
        "Identify a concrete maintenance problem before proposing a change: repeated "
        "responsibilities, difficult state or control flow, or duplication that must "
        "evolve together.",
        "For no-change or defer, cite the specific guard, invariant, algorithm, or tradeoff "
        "that explains the measurement, plus remaining risk. Do not dismiss a finding only "
        "because a score is imperfect, or edit code only to lower it.",
        "For actionable findings, describe the smallest useful change and how to verify "
        "behavior. Re-run under compatible settings; assess readability as well as score movement.",
    )
    disposition_template: str = (
        "Review: <location> | <actionable / defer / no-change> | evidence: <metric and source> "
        "| reason: <problem or justified exception; remaining risk> "
        "| next: <change, check, or none>."
    )
