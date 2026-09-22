"""Conservative syntax anchors for edited clone runs; target code is never executed."""

import ast
from collections import Counter
from dataclasses import dataclass

from slop_measure.domain.evidence import SourceSpan
from slop_measure.domain.source import SourceDocument

_Declaration = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


@dataclass(frozen=True)
class StatementAnchor:
    start: int
    end: int
    syntax: str


@dataclass(frozen=True)
class CloneSyntax:
    owner: tuple[str, ...]
    suite: tuple[str, ...]
    statements: tuple[StatementAnchor, ...]


class CloneSyntaxIndex:
    """Index unique declaration owners and complete statements in one parsed file."""

    def __init__(self, document: SourceDocument) -> None:
        self.statements: list[tuple[tuple[str, ...], tuple[str, ...], ast.stmt]] = []
        self.owners: Counter[tuple[str, ...]] = Counter({(): 1})
        self._visit(ast.parse(document.content), (), ())

    def _visit(self, node: ast.AST, owner: tuple[str, ...], suite: tuple[str, ...]) -> None:
        if isinstance(node, _Declaration):
            owner = (*owner, node.name)
            self.owners[owner] += 1
            suite = ()
        elif isinstance(node, ast.stmt):
            self.statements.append((owner, suite, node))
        for field, value in ast.iter_fields(node):
            for child in value if isinstance(value, list) else (value,):
                if isinstance(child, ast.AST):
                    self._visit(child, owner, (*suite, f"{type(node).__name__}.{field}"))

    def run(self, span: SourceSpan) -> CloneSyntax | None:
        contained = [
            (owner, suite, node)
            for owner, suite, node in self.statements
            if span.start_line <= node.lineno and (node.end_lineno or node.lineno) <= span.end_line
        ]
        owners = {owner for owner, _, _ in contained}
        if len(owners) != 1:
            return None
        owner = next(iter(owners))
        if self.owners[owner] != 1:
            return None
        statements = []
        last_end = 0
        for _, _, node in contained:
            if node.lineno <= last_end:
                continue
            last_end = node.end_lineno or node.lineno
            statements.append(StatementAnchor(node.lineno, last_end, ast.dump(node)))
        return CloneSyntax(owner, contained[0][1], tuple(statements))


def anchored_run(before: CloneSyntax, after: CloneSyntax, lines: dict[int, int]) -> bool:
    """Require a majority of complete statements to retain syntax and line correspondence."""
    if (before.owner, before.suite) != (after.owner, after.suite):
        return False
    new = {(item.start, item.end, item.syntax) for item in after.statements}
    matches = [
        item.syntax
        for item in before.statements
        if (lines.get(item.start), lines.get(item.end), item.syntax) in new
    ]
    # Two distinct statements avoid treating a generic return or repeated boilerplate as identity.
    minimum_distinct_anchors = 2
    return len(set(matches)) >= minimum_distinct_anchors and len(matches) * 2 > max(
        len(before.statements), len(after.statements)
    )
