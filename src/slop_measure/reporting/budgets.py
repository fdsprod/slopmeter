"""Render observed budget counts and the locations that limit assessment."""

from slop_measure.domain.budgets import BudgetReport


def render_budget(budget: BudgetReport) -> str:
    lines = [f"Budget: {budget.state}"]
    for check in budget.checks:
        lines.append(f"  {check.metric}: observed {check.observed}, maximum {check.maximum}")
        for detail in check.incomplete_details:
            location = detail.side.value + " " if detail.side else ""
            if detail.path is not None:
                location += detail.path.root
                if detail.span is not None:
                    location += f":{detail.span.start_line}-{detail.span.end_line}"
            else:
                location += "population"
            lines.append(f"    incomplete [{detail.code}] {location}: {detail.message}")
        if not check.incomplete_details:
            lines.extend(f"    incomplete: {reason}" for reason in check.incomplete_reasons)
    return "\n".join(lines)
