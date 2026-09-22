"""A field name alone does not establish lifecycle or geographic semantics."""

import pytest
from test_change_review import request, roots as shared_roots, write
from typer.testing import CliRunner

from slop_measure import api
from slop_measure.cli import app

roots = shared_roots


@pytest.mark.parametrize("value", ["OH", "IL", "ready"])
def test_literal_state_evidence_has_no_inferred_semantic_domain(roots, value):
    write(roots[1], "test_projection.py", f'assert facts.state == "{value}"\n')
    selected = request(roots, languages=("python",))
    scored = api.compare(selected).model_dump_json()

    report = api.review_change(selected)

    wire = report.model_dump(mode="json")
    assert len(wire["state_dispatch"]) == 1
    occurrence = wire["state_dispatch"][0]["current"]
    assert occurrence["subject"] == "facts.state"
    assert occurrence["values"] == [value]
    assert occurrence["context"] == "assertion"
    interpretation = " ".join(wire["state_dispatch_interpretation"]).lower()
    assert "semantic" in interpretation and "unknown" in interpretation
    assert "geographic" in interpretation
    assert "review enum members" not in interpretation
    assert api.compare(selected).model_dump_json() == scored
    assert type(report).model_validate_json(report.model_dump_json()) == report


def test_terminal_labels_literal_field_comparisons_without_prescribing_a_lifecycle(roots):
    write(
        roots[1],
        "flow.py",
        'assert facts.state == "OH"\nif job.state == "ready":\n    start()\n',
    )

    result = CliRunner().invoke(app, ["changes", *map(str, roots), "--lang", "py"])

    assert result.exit_code == 0, result.output
    output = " ".join(result.stdout.lower().split())
    assert "literal state-field comparisons" in output
    assert "semantic" in output and "unknown" in output
    assert "oh" in output and "ready" in output
    assert "review enum members" not in output
