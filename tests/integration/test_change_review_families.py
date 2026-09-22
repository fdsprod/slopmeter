"""Clone membership and exception fallback changes retain their distinct evidence."""

import json

import pytest
from test_change_review import request, roots as shared_roots, write
from test_git_comparison import git
from typer.testing import CliRunner

from slop_measure import api
from slop_measure.cli import app
from slop_measure.domain.reports import ComparisonCohortReport

roots = shared_roots
CLONE = "def first(source):\n    value = source + 1\n    return value\n"
FALLBACK = (
    "def fetch(client):\n"
    "    try:\n"
    "        result = client.read()\n"
    "    except OSError:\n"
    "        return []\n"
    "    return result\n"
)


def clone_report(roots):
    return api.review_change(request(roots, clone_min_sloc=2))


def clone_changes(report) -> list[dict]:
    return report.model_dump(mode="json")["clones"]


def member_paths(occurrences: list[dict]) -> set[str]:
    return {item["member"]["path"] for item in occurrences}


def test_new_copy_expands_existing_group_by_one_member(roots) -> None:
    for root in roots:
        write(root, "a.py", CLONE)
        write(root, "b.py", CLONE.replace("first", "second"))
    write(roots[1], "c.py", CLONE.replace("first", "third"))

    changes = clone_changes(clone_report(roots))

    assert len(changes) == 1
    group = changes[0]
    assert group["state"] == "expanded" and group["added"] == 1 and group["removed"] == 0
    assert member_paths(group["baseline"]) == {"a.py", "b.py"}
    assert member_paths(group["current"]) == {"a.py", "b.py", "c.py"}
    assert sorted(member["state"] for member in group["members"]) == [
        "introduced",
        "persisted",
        "persisted",
    ]


def test_singleton_becoming_a_clone_group_counts_only_the_new_copy(roots) -> None:
    for root in roots:
        write(root, "a.py", CLONE)
    write(roots[1], "b.py", CLONE.replace("first", "second"))

    changes = clone_changes(clone_report(roots))

    assert len(changes) == 1
    group = changes[0]
    assert group["state"] == "introduced" and group["added"] == 1
    assert member_paths(group["baseline"]) == {"a.py"}
    assert member_paths(group["current"]) == {"a.py", "b.py"}


def test_clone_line_shifts_and_exact_rename_preserve_both_members(roots) -> None:
    write(roots[0], "a.py", CLONE)
    write(roots[0], "b.py", CLONE.replace("first", "second"))
    write(roots[1], "a.py", "# Heading\n" + CLONE)
    write(roots[1], "renamed.py", CLONE.replace("first", "second"))

    changes = clone_changes(clone_report(roots))

    assert len(changes) == 1
    group = changes[0]
    assert group["state"] == "persisted" and group["added"] == group["removed"] == 0
    assert member_paths(group["baseline"]) == {"a.py", "b.py"}
    assert member_paths(group["current"]) == {"a.py", "renamed.py"}
    shifted = next(
        item for item in group["members"] if item["baseline"]["member"]["path"] == "a.py"
    )
    assert shifted["current"]["member"]["span"]["start_line"] == (
        shifted["baseline"]["member"]["span"]["start_line"] + 1
    )


def test_deleting_one_of_two_copies_removes_group_but_retains_surviving_source(roots) -> None:
    for root in roots:
        write(root, "a.py", CLONE)
    write(roots[0], "b.py", CLONE.replace("first", "second"))

    changes = clone_changes(clone_report(roots))

    assert len(changes) == 1
    group = changes[0]
    assert group["state"] == "removed" and group["removed"] == 1 and group["added"] == 0
    assert member_paths(group["current"]) == {"a.py"}


@pytest.mark.parametrize("missing_source", ["def broken(:\n", "# @generated\n" + CLONE])
def test_missing_clone_analysis_does_not_claim_group_or_member_removal(roots, missing_source):
    for root in roots:
        write(root, "a.py", CLONE)
    write(roots[0], "b.py", CLONE.replace("first", "second"))
    write(roots[1], "b.py", missing_source)

    changes = clone_changes(clone_report(roots))

    assert len(changes) == 1
    group = changes[0]
    assert group["state"] == "unresolved" and group["removed"] == 0
    unresolved = [member for member in group["members"] if member["state"] == "unresolved"]
    assert unresolved and member_paths(unresolved[0]["baseline"]) == {"b.py"}
    assert unresolved[0]["reason"].strip()


@pytest.mark.parametrize("introduced", [True, False])
def test_exception_fallback_addition_and_explicit_rethrow_removal(roots, introduced) -> None:
    clean = FALLBACK.replace("return []", "raise")
    write(roots[0], "fetch.py", clean if introduced else FALLBACK)
    write(roots[1], "fetch.py", FALLBACK if introduced else clean)

    report = api.review_change(request(roots))

    errors = report.model_dump(mode="json")["errors"]
    assert len(errors) == 1
    state, side = ("introduced", "current") if introduced else ("removed", "baseline")
    assert errors[0]["state"] == state
    assert errors[0][side]["path"] == "fetch.py"
    assert errors[0][side]["symbol"] == "fetch"
    assert errors[0][side]["finding"]["fallback_kind"] == "empty-list"
    assert report.error_summary[state] == 1


def test_error_line_shift_preserves_finding_and_owned_expression_locations(roots) -> None:
    write(roots[0], "fetch.py", FALLBACK)
    write(roots[1], "fetch.py", "# Heading\n\n" + FALLBACK)

    errors = api.review_change(request(roots)).model_dump(mode="json")["errors"]

    assert len(errors) == 1 and errors[0]["state"] == "persisted"
    for side, start in (("baseline", 5), ("current", 7)):
        occurrence = errors[0][side]
        assert occurrence["finding"]["fallback"]["span"]["start_line"] == start
        assert len(occurrence["source_sha256"]) == 64
    assert errors[0]["baseline"]["source_sha256"] != errors[0]["current"]["source_sha256"]


def test_changed_fallback_at_same_handler_is_changed(roots) -> None:
    write(roots[0], "fetch.py", FALLBACK)
    write(roots[1], "fetch.py", FALLBACK.replace("return []", "return {}"))

    errors = api.review_change(request(roots)).model_dump(mode="json")["errors"]

    assert len(errors) == 1 and errors[0]["state"] == "changed"
    assert errors[0]["baseline"]["finding"]["fallback_kind"] == "empty-list"
    assert errors[0]["current"]["finding"]["fallback_kind"] == "empty-dict"


@pytest.mark.parametrize(
    "replacement",
    [
        "return client.default",
        "if client.ready:\n            return []\n        return None",
    ],
)
def test_unresolved_handler_transition_cannot_be_reported_as_removed(roots, replacement) -> None:
    write(roots[0], "fetch.py", FALLBACK)
    write(roots[1], "fetch.py", FALLBACK.replace("return []", replacement))

    report = api.review_change(request(roots))

    wire = report.model_dump(mode="json")
    assert len(wire["errors"]) == 1 and wire["errors"][0]["state"] == "unresolved"
    assert report.error_summary["removed"] == 0
    current = next(item["detail"] for item in wire["error_coverage"] if item["source"] == "current")
    assert current["path"] == "fetch.py" and current["state"] == "analyzed"
    assert current["handlers"][0]["state"] == "unresolved"
    assert current["handlers"][0]["reason"].strip()


def test_failed_error_file_preserves_unresolved_evidence_and_failed_coverage(roots) -> None:
    write(roots[0], "fetch.py", FALLBACK)
    write(roots[1], "fetch.py", "def broken(:\n")

    report = api.review_change(request(roots))

    wire = report.model_dump(mode="json")
    assert len(wire["errors"]) == 1 and wire["errors"][0]["state"] == "unresolved"
    assert report.error_summary["removed"] == 0
    failed = next(item["detail"] for item in wire["error_coverage"] if item["source"] == "current")
    assert failed["state"] == "failed" and failed["path"] == "fetch.py"


def test_families_are_deterministic_independent_and_do_not_change_compare_scores(roots) -> None:
    write(roots[0], "fetch.py", FALLBACK)
    write(roots[1], "fetch.py", FALLBACK)
    for root in roots:
        write(root, "a.py", CLONE)
    write(roots[1], "b.py", CLONE.replace("first", "second"))
    selected = request(roots, clone_min_sloc=2)
    comparison = api.compare(selected).model_dump_json()

    report = api.review_change(selected)

    assert report.model_dump_json() == api.review_change(selected).model_dump_json()
    assert type(report).model_validate_json(report.model_dump_json()) == report
    assert api.compare(selected).model_dump_json() == comparison
    assert report.error_summary["persisted"] == 1
    assert report.clones
    assert report.summary == {
        state: sum(change.state == state for change in report.patterns)
        for state in ("introduced", "removed", "persisted", "changed", "unresolved")
    }


def test_git_error_comparison_uses_committed_source_and_preserves_worktree(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Family test")
    git(root, "config", "user.email", "family@example.invalid")
    write(root, "fetch.py", FALLBACK.replace("return []", "raise"))
    git(root, "add", ".")
    git(root, "commit", "-m", "baseline")
    write(root, "fetch.py", FALLBACK)
    git(root, "add", ".")
    git(root, "commit", "-m", "fallback")
    revision = git(root, "rev-parse", "HEAD").decode().strip()
    write(root, "fetch.py", "dirty = True\n")
    index = (root / ".git/index").read_bytes()
    status = git(root, "status", "--porcelain=v1")

    result = CliRunner().invoke(app, ["changes", "HEAD~1", "HEAD", "--repo", str(root), "--json"])

    assert result.exit_code == 0, result.output
    wire = json.loads(result.stdout)
    assert wire["analysis"]["current"]["revision"] == revision
    assert len(wire["errors"]) == 1 and wire["errors"][0]["state"] == "introduced"
    assert wire["errors"][0]["current"]["finding"]["fallback"]["expression"] == "[]"
    assert (root / "fetch.py").read_text(encoding="utf-8") == "dirty = True\n"
    assert (root / ".git/index").read_bytes() == index
    assert git(root, "status", "--porcelain=v1") == status


def test_git_renamed_unparseable_clone_member_is_unresolved_not_removed(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    root = tmp_path / "renamed-clone"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Clone rename test")
    git(root, "config", "user.email", "clone@example.invalid")
    source = (
        "def first(source):\n"
        "    value = source + 1\n"
        "    value *= 2\n"
        "    value -= 3\n"
        "    value //= 4\n"
        "    value += 5\n"
        "    return value\n"
    )
    write(root, "a.py", source)
    write(root, "b.py", source.replace("first", "second"))
    git(root, "add", ".")
    git(root, "commit", "-m", "two copies")
    baseline = git(root, "rev-parse", "HEAD").decode().strip()
    git(root, "mv", "b.py", "renamed.py")
    write(root, "renamed.py", source.replace("first", "second") + "\ndef broken(:\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "rename with unparseable edit")
    selected = api.ComparisonRequest(
        baseline=api.GitSourceReference(root=root, revision=baseline),
        current=api.GitSourceReference(root=root, revision="HEAD"),
        config=api.AnalysisConfig(clone_min_sloc=2),
    )
    comparison = api.compare(selected)
    pairs = [
        change.pair
        for cohort in comparison.cohorts
        if isinstance(cohort, ComparisonCohortReport)
        for change in cohort.changes
    ]
    assert any(
        pair.kind == "renamed"
        and pair.baseline_path.root == "b.py"
        and pair.current_path.root == "renamed.py"
        for pair in pairs
    )

    groups = clone_changes(api.review_change(selected))

    assert len(groups) == 1 and groups[0]["state"] == "unresolved"
    assert groups[0]["removed"] == 0
    missing = [member for member in groups[0]["members"] if member["state"] == "unresolved"]
    assert len(missing) == 1 and member_paths(missing[0]["baseline"]) == {"b.py"}
