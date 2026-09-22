"""Coordinated edits preserve copy identity without implying review approval."""

from pathlib import Path

import pytest
from test_git_comparison import git

from slop_measure import api
from slop_measure.application.budgets import evaluate_budget
from slop_measure.application.reviews import apply_reviews, write_clone_review
from slop_measure.domain.budgets import BudgetLimit, BudgetMetric, BudgetPolicy
from slop_measure.domain.reviews import ReviewDisposition

ORIGINAL = """def publish(producer, topic, payload, headers):
    encoded = payload.encode()
    producer.poll(0)
    producer.produce(topic, encoded)
    remaining = producer.flush()
    verify(remaining)
    record(topic)
    return remaining
"""
EDITED = ORIGINAL.replace(
    "producer.produce(topic, encoded)",
    "producer.produce(topic, encoded, headers=[*headers.items()])",
)


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    result = tmp_path / "baseline", tmp_path / "current"
    for root in result:
        root.mkdir()
    return result


def copies(root: Path, source: str, count: int = 4) -> None:
    for index in range(count):
        (root / f"publisher_{index}.py").write_text(source, encoding="utf-8")


def compare(roots: tuple[Path, Path]):
    return api.review_change(
        api.ComparisonRequest(
            baseline=api.DirectorySourceReference(root=roots[0]),
            current=api.DirectorySourceReference(root=roots[1]),
            config=api.AnalysisConfig(calibration_profile="__raw__"),
        )
    )


def snapshot(root: Path):
    return api.scan(
        api.SnapshotRequest(
            target=api.DirectorySourceReference(root=root),
            config=api.AnalysisConfig(calibration_profile="__raw__"),
        )
    )


def clone_budget(report):
    return evaluate_budget(
        report,
        BudgetPolicy(limits=(BudgetLimit(metric=BudgetMetric.ADDED_CLONE_MEMBERS, maximum=0),)),
    )


def test_coordinated_edit_is_changed_duplication_and_not_four_new_copies(roots):
    copies(roots[0], ORIGINAL)
    copies(roots[1], EDITED)
    report = compare(roots)
    assert len(report.clones) == 1
    group = report.clones[0].model_dump(mode="json")
    assert group["state"] == "changed"
    assert group["added"] == group["removed"] == 0
    assert group["modified"] == 4
    assert [member["state"] for member in group["members"]] == ["changed"] * 4
    assert group["baseline_fingerprint"] != group["current_fingerprint"]
    assert group["fingerprint"] == group["current_fingerprint"]
    assert {item["member"]["path"] for item in group["baseline"]} == {
        item["member"]["path"] for item in group["current"]
    }
    budget = clone_budget(report)
    assert budget.checks[0].observed == 0 and budget.state.value == "pass"
    assert type(report).model_validate_json(report.model_dump_json()) == report


def test_coordinated_edit_plus_fifth_copy_counts_only_the_new_copy(roots):
    copies(roots[0], ORIGINAL)
    copies(roots[1], EDITED, count=5)
    report = compare(roots)
    assert len(report.clones) == 1
    group = report.clones[0].model_dump(mode="json")
    assert group["state"] == "expanded"
    assert (group["added"], group["removed"], group["modified"]) == (1, 0, 4)
    budget = clone_budget(report)
    assert budget.checks[0].observed == 1 and budget.state.value == "exceeded"
    assert budget.checks[0].evidence[0].path.root == "publisher_4.py"


def test_line_shift_does_not_destroy_modified_member_correspondence(roots):
    copies(roots[0], ORIGINAL)
    copies(roots[1], "# Header added during the edit.\n\n" + EDITED)
    report = compare(roots)
    assert len(report.clones) == 1
    group = report.clones[0].model_dump(mode="json")
    assert group["state"] == "changed" and group["modified"] == 4
    for member in group["members"]:
        assert member["current"]["member"]["span"]["start_line"] == (
            member["baseline"]["member"]["span"]["start_line"] + 2
        )


def test_group_split_retains_uncertainty_instead_of_inventing_copy_additions(roots):
    copies(roots[0], ORIGINAL)
    copies(roots[1], EDITED)
    alternative = EDITED.replace("    record(topic)\n", "    record(topic)\n    audit(payload)\n")
    for index in (2, 3):
        (roots[1] / f"publisher_{index}.py").write_text(alternative, encoding="utf-8")
    report = compare(roots)
    assert any(group.state.value == "unresolved" for group in report.clones)
    assert clone_budget(report).state.value == "incomplete"


@pytest.mark.parametrize("declaration", ["def classify(values):", ORIGINAL.splitlines()[0]])
def test_unrelated_replacements_in_same_paths_do_not_establish_modified_continuity(
    roots, declaration
):
    copies(roots[0], ORIGINAL)
    copies(
        roots[1],
        declaration + "\n"
        "    total = sum(values)\n"
        "    smallest = min(values)\n"
        "    largest = max(values)\n"
        "    spread = largest - smallest\n"
        "    average = total / len(values)\n"
        "    label = str(average)\n"
        "    return label, spread\n",
    )
    report = compare(roots)
    assert report.clones
    assert all(group.state.value not in {"changed", "persisted"} for group in report.clones)
    assert clone_budget(report).state.value != "pass"


def test_git_rename_with_coordinated_edit_keeps_existing_copy_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Clone continuity test")
    git(root, "config", "user.email", "clone@example.invalid")
    copies(root, ORIGINAL)
    git(root, "add", ".")
    git(root, "commit", "-m", "baseline copies")
    copies(root, EDITED)
    git(root, "mv", "publisher_0.py", "renamed.py")
    git(root, "add", ".")
    git(root, "commit", "-m", "update copies and move one publisher")
    report = api.review_change(
        api.ComparisonRequest(
            baseline=api.GitSourceReference(root=root, revision="HEAD~1"),
            current=api.GitSourceReference(root=root, revision="HEAD"),
            config=api.AnalysisConfig(calibration_profile="__raw__"),
        )
    )
    assert len(report.clones) == 1
    group = report.clones[0].model_dump(mode="json")
    assert group["state"] == "changed" and group["modified"] == 4
    moved = next(
        item for item in group["members"] if item["current"]["member"]["path"] == "renamed.py"
    )
    assert moved["baseline"]["member"]["path"] == "publisher_0.py"
    assert clone_budget(report).checks[0].observed == 0


def test_exact_fingerprint_survives_comment_shift_and_exact_directory_rename(roots):
    copies(roots[0], ORIGINAL)
    copies(roots[1], ORIGINAL)
    (roots[1] / "publisher_0.py").rename(roots[1] / "renamed.py")
    shifted = roots[1] / "publisher_1.py"
    shifted.write_text("# Heading\n" + ORIGINAL, encoding="utf-8")
    report = compare(roots)
    assert len(report.clones) == 1
    assert report.clones[0].state.value == "persisted"
    assert clone_budget(report).checks[0].observed == 0


def test_parse_failure_remains_uncertain_after_other_members_change(roots):
    copies(roots[0], ORIGINAL)
    copies(roots[1], EDITED)
    (roots[1] / "publisher_0.py").write_text("def broken(:\n", encoding="utf-8")
    report = compare(roots)
    assert any(group.state.value == "unresolved" for group in report.clones)
    assert clone_budget(report).state.value == "incomplete"


def test_changed_source_still_invalidates_saved_review_without_changing_scores(roots, tmp_path):
    copies(roots[0], ORIGINAL)
    copies(roots[1], EDITED)
    baseline = snapshot(roots[0])
    current = snapshot(roots[1])
    before = current.model_dump_json()
    store = write_clone_review(
        tmp_path / "reviews.json",
        baseline,
        baseline.clone_groups[0].id,
        disposition=ReviewDisposition.NO_CHANGE,
        reason="Separate deployment ownership.",
    )
    compare(roots)
    assert apply_reviews(current, store).review_results[0].state == "stale"
    assert current.model_dump_json() == before
    assert snapshot(roots[1]).model_dump_json() == before
