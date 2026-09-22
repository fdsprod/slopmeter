"""Conservative syntax context for findings, without importing analyzed source."""

import ast

from slop_measure.domain.evidence import PatternFinding
from slop_measure.domain.source import SourceDocument


def pattern_contexts(
    document: SourceDocument, findings: tuple[PatternFinding, ...]
) -> dict[PatternFinding, tuple[str, str]]:
    """Keep enclosing statement syntax and lexical scope, ignoring source formatting."""
    tree = ast.parse(document.content)
    contexts: dict[PatternFinding, tuple[str, str]] = {}

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope = (*scope, node.name)
        if isinstance(node, ast.stmt):
            for finding in findings:
                if (
                    node.lineno <= finding.span.start_line
                    and (node.end_lineno or node.lineno) >= finding.span.end_line
                ):
                    contexts[finding] = (".".join(scope), ast.dump(node, include_attributes=False))
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(tree, ())
    return contexts
