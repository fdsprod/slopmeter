"""Raw state comparisons are source-located review evidence, not proof of a defect."""

import json
from hashlib import sha256

import pytest
from test_change_review import request, roots as shared_roots, write
from typer.testing import CliRunner

from slop_measure import api
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
