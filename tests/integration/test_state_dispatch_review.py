"""Raw state comparisons are source-located review evidence, not proof of a defect."""

import json
from hashlib import sha256

import pytest
from test_change_review import request, roots as shared_roots, write
from test_git_comparison import git
from typer.testing import CliRunner

from slop_measure import api
from slop_measure.api import AnalysisConfig, ComparisonRequest, GitSourceReference
from slop_measure.cli import app

roots = shared_roots


def dispatch(report) -> list[dict]:
    return report.model_dump(mode="json")["state_dispatch"]


def test_exact_raw_state_assertion_retains_current_source_evidence(roots):
    source = 'assert item.state != "unresolved"\n'
    write(roots[1], "test_result.py", source)

    report = api.review_change(request(roots, languages=("python",)))

    changes = dispatch(report)
    assert len(changes) == 1 and changes[0]["state"] == "introduced"
    occurrence = changes[0]["current"]
    assert occurrence["path"] == "test_result.py"
    assert occurrence["span"] == {"start_line": 1, "end_line": 1}
    assert occurrence["source_sha256"] == sha256(source.encode()).hexdigest()
    assert occurrence["language"] == "python" and occurrence["cohort"] == "test"
    assert occurrence["subject"] == "item.state"
    assert occurrence["operator"] == "ne"
    assert occurrence["values"] == ["unresolved"]
    assert occurrence["context"] == "assertion"
    assert report.state_dispatch_summary == {
        "introduced": 1,
        "removed": 0,
        "persisted": 0,
        "changed": 0,
        "unresolved": 0,
    }


@pytest.mark.parametrize(
    "source,operator,context,values",
    [
        ('if item.state == "ready":\n    pass\n', "eq", "condition", {"ready"}),
        ('while item.state != "done":\n    break\n', "ne", "condition", {"done"}),
        ('assert "unknown" != item.state\n', "ne", "assertion", {"unknown"}),
        ('if "ready" == item.state:\n    pass\n', "eq", "condition", {"ready"}),
        ('assert item.state in ("done", "failed")\n', "in", "assertion", {"done", "failed"}),
        (
            'if item.state not in {"done", "failed"}:\n    pass\n',
            "not-in",
            "condition",
            {"done", "failed"},
        ),
        (
            'if item.state in ["queued", "running"]:\n    pass\n',
            "in",
            "condition",
            {"queued", "running"},
        ),
    ],
)
def test_direct_conditions_and_literal_membership_are_reported(
    roots, source, operator, context, values
):
    write(roots[1], "flow.py", source)

    changes = dispatch(api.review_change(request(roots, languages=("python",))))

    assert len(changes) == 1 and changes[0]["state"] == "introduced"
    occurrence = changes[0]["current"]
    assert occurrence["subject"] == "item.state"
    assert occurrence["operator"] == operator
    assert occurrence["context"] == context
    assert set(occurrence["values"]) == values


def test_multiline_comparison_location_excludes_the_condition_body(roots):
    source = 'if (\n    item.state\n    == "ready"\n):\n    run()\n'
    write(roots[1], "flow.py", source)

    changes = dispatch(api.review_change(request(roots, languages=("python",))))

    assert changes[0]["current"]["span"] == {"start_line": 2, "end_line": 3}


@pytest.mark.parametrize(
    "source",
    [
        "assert isinstance(item, KnownRework)\n",
        "assert item.state is State.UNRESOLVED\n",
        "if item.state == State.READY:\n    pass\n",
        'assert item.name == "unresolved"\n',
        'if state == "ready":\n    pass\n',
        "assert item.state == expected_state\n",
        'if item.state in ("ready", State.FAILED):\n    pass\n',
        'value = item.state == "ready"\n',
        "if item.state in ():\n    pass\n",
    ],
)
def test_enum_checks_other_fields_and_unsupported_comparisons_remain_outside_scope(roots, source):
    write(roots[1], "flow.py", source)

    report = api.review_change(request(roots, languages=("python",)))

    assert dispatch(report) == []
    assert all(count == 0 for count in report.state_dispatch_summary.values())


def test_line_shift_preserves_raw_state_comparison_with_both_locations(roots):
    source = 'def inspect(item):\n    assert item.state != "unresolved"\n'
    write(roots[0], "flow.py", source)
    write(roots[1], "flow.py", "# Heading\n\n" + source)

    report = api.review_change(request(roots, languages=("python",)))

    changes = dispatch(report)
    assert len(changes) == 1 and changes[0]["state"] == "persisted"
    assert changes[0]["baseline"]["span"]["start_line"] == 2
    assert changes[0]["current"]["span"]["start_line"] == 4
    assert changes[0]["baseline"]["source_sha256"] != changes[0]["current"]["source_sha256"]
    assert report.state_dispatch_summary["introduced"] == 0


def test_literal_change_at_the_same_unique_comparison_is_changed(roots):
    write(roots[0], "flow.py", 'def inspect(item):\n    assert item.state != "unresolved"\n')
    write(roots[1], "flow.py", 'def inspect(item):\n    assert item.state != "failed"\n')

    changes = dispatch(api.review_change(request(roots, languages=("python",))))

    assert len(changes) == 1 and changes[0]["state"] == "changed"
    assert changes[0]["baseline"]["values"] == ["unresolved"]
    assert changes[0]["current"]["values"] == ["failed"]


def test_switch_to_enum_member_removes_only_the_raw_comparison_evidence(roots):
    write(roots[0], "flow.py", 'assert item.state != "unresolved"\n')
    write(roots[1], "flow.py", "assert item.state is not State.UNRESOLVED\n")

    report = api.review_change(request(roots, languages=("python",)))

    changes = dispatch(report)
    assert len(changes) == 1 and changes[0]["state"] == "removed"
    assert changes[0]["baseline"]["subject"] == "item.state"
    assert "current" not in changes[0]
    assert report.state_dispatch_summary["removed"] == 1


@pytest.mark.parametrize("failed_side", [0, 1])
def test_parse_failure_does_not_prove_raw_comparison_introduction_or_removal(roots, failed_side):
    write(roots[1 - failed_side], "flow.py", 'assert item.state != "unresolved"\n')
    write(roots[failed_side], "flow.py", "def broken(:\n")

    report = api.review_change(request(roots, languages=("python",)))

    changes = dispatch(report)
    assert len(changes) == 1 and changes[0]["state"] == "unresolved"
    assert changes[0]["reason"].strip()
    assert report.state_dispatch_summary["introduced"] == 0
    assert report.state_dispatch_summary["removed"] == 0


def test_review_is_deterministic_unscored_and_does_not_execute_source(roots, tmp_path):
    marker = tmp_path / "executed"
    source = (
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
        'assert item.state != "unresolved"\n'
    )
    write(roots[1], "flow.py", source)
    selected = request(roots, languages=("python",))
    scored_before = api.compare(selected).model_dump_json()

    report = api.review_change(selected)

    assert not marker.exists()
    assert dispatch(report)
    assert report.model_dump_json() == api.review_change(selected).model_dump_json()
    assert api.compare(selected).model_dump_json() == scored_before
    assert not {"score", "cohorts", "slop_score"} & report.model_dump(mode="json").keys()
    assert type(report).model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize("count", [0, True])
def test_imported_state_dispatch_summary_cannot_contradict_source_evidence(roots, count):
    write(roots[1], "flow.py", 'assert item.state != "unresolved"\n')
    report = api.review_change(request(roots, languages=("python",)))
    wire = report.model_dump(mode="json")
    wire["state_dispatch_summary"]["introduced"] = count

    with pytest.raises(ValueError):
        type(report).model_validate(wire)


def test_existing_changes_json_command_includes_the_same_review_evidence(roots):
    write(roots[1], "flow.py", 'assert item.state != "unresolved"\n')
    result = CliRunner().invoke(
        app,
        ["changes", *map(str, roots), "--lang", "py", "--json"],
    )
    assert result.exit_code == 0, result.output
    wire = json.loads(result.stdout)
    assert len(wire["state_dispatch"]) == 1
    assert wire == api.review_change(request(roots, languages=("python",))).model_dump(mode="json")


def test_distinct_comparisons_on_one_line_retain_separate_occurrence_ownership(roots):
    write(roots[1], "flow.py", 'assert item.state == "ready" or item.state == "done"\n')

    report = api.review_change(request(roots, languages=("python",)))

    changes = dispatch(report)
    assert len(changes) == 2 and all(item["state"] == "introduced" for item in changes)
    assert {tuple(item["current"]["values"]) for item in changes} == {("ready",), ("done",)}
    assert all(item["current"]["span"]["start_line"] == 1 for item in changes)
    assert report.state_dispatch_summary["introduced"] == 2
    assert type(report).model_validate_json(report.model_dump_json()) == report


def test_repeated_signatures_keep_existing_sites_when_another_occurrence_is_added(roots):
    source = (
        "def inspect(item):\n"
        '    assert item.state != "unknown"\n'
        "    audit()\n"
        '    assert item.state != "unknown"\n'
    )
    write(roots[0], "flow.py", source)
    write(roots[1], "flow.py", source + '    finalize()\n    assert item.state != "unknown"\n')

    report = api.review_change(request(roots, languages=("python",)))

    changes = dispatch(report)
    assert sorted(item["state"] for item in changes) == ["introduced", "persisted", "persisted"]
    persisted = [item for item in changes if item["state"] == "persisted"]
    assert {
        (item["baseline"]["span"]["start_line"], item["current"]["span"]["start_line"])
        for item in persisted
    } == {(2, 2), (4, 4)}
    added = next(item for item in changes if item["state"] == "introduced")
    assert added["current"]["span"]["start_line"] == 6


def test_git_renamed_failed_counterpart_does_not_prove_comparison_removal(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Dispatch test")
    git(repo, "config", "user.email", "dispatch@example.invalid")
    source = (
        "def inspect(item):\n"
        "    first = 1\n"
        "    second = first + 2\n"
        "    third = second + 3\n"
        "    fourth = third + 4\n"
        '    assert item.state != "unresolved"\n'
        "    return fourth\n"
    )
    write(repo, "old.py", source)
    git(repo, "add", ".")
    git(repo, "commit", "-m", "baseline")
    git(repo, "mv", "old.py", "new.py")
    write(repo, "new.py", source.replace("def inspect(item):", "def inspect(item:"))
    git(repo, "add", ".")
    git(repo, "commit", "-m", "rename and introduce syntax error")
    assert git(repo, "diff", "--name-status", "-M", "HEAD~1", "HEAD").startswith(b"R")

    report = api.review_change(
        ComparisonRequest(
            baseline=GitSourceReference(root=repo, revision="HEAD~1"),
            current=GitSourceReference(root=repo, revision="HEAD"),
            config=AnalysisConfig(languages=frozenset({"python"})),
        )
    )

    changes = dispatch(report)
    assert len(changes) == 1 and changes[0]["state"] == "unresolved"
    assert changes[0]["baseline"][0]["path"] == "old.py"
    assert changes[0]["reason"].strip()
    assert report.state_dispatch_summary["removed"] == 0


def test_excluded_counterpart_does_not_prove_comparison_removal(roots):
    source = 'assert item.state != "unresolved"\n'
    write(roots[0], "flow.py", source)
    write(roots[1], "flow.py", "# @generated\n" + source)

    report = api.review_change(request(roots, languages=("python",)))

    changes = dispatch(report)
    assert len(changes) == 1 and changes[0]["state"] == "unresolved"
    assert (
        report.state_dispatch_summary["introduced"] == report.state_dispatch_summary["removed"] == 0
    )


def test_multiple_rewritten_comparisons_in_one_scope_remain_ambiguous(roots):
    write(
        roots[0],
        "flow.py",
        (
            'def inspect(item):\n    assert item.state == "ready"\n    assert item.state == "failed"\n'
        ),
    )
    write(
        roots[1],
        "flow.py",
        (
            'def inspect(item):\n    assert other.state != "queued"\n    assert another.state != "gone"\n'
        ),
    )

    report = api.review_change(request(roots, languages=("python",)))

    changes = dispatch(report)
    assert changes and all(item["state"] == "unresolved" for item in changes)
    assert sum(len(item["baseline"]) for item in changes) == 2
    assert sum(len(item["current"]) for item in changes) == 2
    assert all(item["reason"].strip() for item in changes)


def test_imported_report_rejects_duplicate_comparison_ownership(roots):
    write(roots[1], "flow.py", 'assert item.state != "unresolved"\n')
    report = api.review_change(request(roots, languages=("python",)))
    wire = report.model_dump(mode="json")
    wire.pop("state_dispatch_summary")
    wire["state_dispatch"].append(wire["state_dispatch"][0])

    with pytest.raises(ValueError):
        type(report).model_validate(wire)
