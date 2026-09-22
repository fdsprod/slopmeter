"""Find direct raw-string state tests without resolving or executing their receivers."""

import ast

from slop_measure.domain.evidence import SourceSpan
from slop_measure.domain.source import SourceDocument
from slop_measure.domain.state_dispatch import (
    DispatchContext,
    StateDispatchOccurrence,
    StateOperator,
)


def _string(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _comparison(node: ast.Compare):
    if len(node.ops) != 1:
        return None
    left, right, operator = node.left, node.comparators[0], node.ops[0]
    if isinstance(operator, (ast.Eq, ast.NotEq)) and _string(left) is not None:
        left, right = right, left
    if not isinstance(left, ast.Attribute) or left.attr != "state":
        return None
    if isinstance(operator, (ast.Eq, ast.NotEq)) and (value := _string(right)) is not None:
        return (
            left,
            StateOperator.EQ if isinstance(operator, ast.Eq) else StateOperator.NE,
            (value,),
        )
    if (
        isinstance(operator, (ast.In, ast.NotIn))
        and isinstance(right, (ast.Tuple, ast.List, ast.Set))
        and right.elts
        and all(_string(item) is not None for item in right.elts)
    ):
        values = tuple(
            sorted({value for item in right.elts if (value := _string(item)) is not None})
        )
        return (
            left,
            StateOperator.IN if isinstance(operator, ast.In) else StateOperator.NOT_IN,
            values,
        )
    return None


def inspect_state_dispatch(document: SourceDocument) -> tuple[StateDispatchOccurrence, ...]:
    """Inspect only comparisons directly contained in assert, if, or while tests."""
    tree = ast.parse(document.content)
    result: list[StateDispatchOccurrence] = []

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope = (*scope, node.name)
        if isinstance(node, (ast.Assert, ast.If, ast.While)):
            context = (
                DispatchContext.ASSERTION
                if isinstance(node, ast.Assert)
                else DispatchContext.CONDITION
            )
            # Assignments and deferred expressions are outside this rule's contract.
            tests = [node.test]
            while tests:
                test = tests.pop()
                if isinstance(test, ast.BoolOp):
                    tests.extend(reversed(test.values))
                elif isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                    tests.append(test.operand)
                elif isinstance(test, ast.Compare) and (details := _comparison(test)):
                    subject, operator, values = details
                    result.append(
                        StateDispatchOccurrence(
                            path=document.path,
                            span=SourceSpan(
                                start_line=test.lineno, end_line=test.end_lineno or test.lineno
                            ),
                            start_column=test.col_offset,
                            end_column=test.end_col_offset
                            if test.end_col_offset is not None
                            else test.col_offset,
                            source_sha256=document.content_hash,
                            cohort=document.cohort,
                            symbol=".".join(scope),
                            subject=ast.unparse(subject),
                            operator=operator,
                            values=values,
                            context=context,
                        )
                    )
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(tree, ())
    return tuple(result)
