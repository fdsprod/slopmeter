"""Extract Python declarations from source syntax without importing target modules."""

import ast
from copy import copy
from dataclasses import dataclass
from hashlib import sha256

from slop_measure.domain.evidence import SourceSpan
from slop_measure.domain.source import SourceDocument
from slop_measure.domain.surface import SymbolOccurrence


@dataclass(frozen=True)
class SymbolSyntax:
    occurrence: SymbolOccurrence
    rename_fingerprint: str


def _fingerprint(node: ast.AST) -> str:
    return sha256(ast.dump(node, include_attributes=False).encode("utf-8")).hexdigest()


def extract_symbols(document: SourceDocument) -> tuple[SymbolSyntax, ...]:
    """Keep names, values, annotations, decorators, and nested declaration syntax."""
    tree = ast.parse(document.content)
    symbols = []

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope = (*scope, node.name)
            renamed = copy(node)
            renamed.name = "__declaration_name__"
            symbols.append(
                SymbolSyntax(
                    occurrence=SymbolOccurrence(
                        cohort=document.cohort,
                        path=document.path,
                        kind="class" if isinstance(node, ast.ClassDef) else "function",
                        qualified_name=".".join(scope),
                        span=SourceSpan(
                            start_line=min(
                                [node.lineno, *(item.lineno for item in node.decorator_list)]
                            ),
                            end_line=node.end_lineno or node.lineno,
                        ),
                        source_sha256=document.content_hash,
                        ast_fingerprint=_fingerprint(node),
                    ),
                    rename_fingerprint=_fingerprint(renamed),
                )
            )
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(tree, ())
    return tuple(symbols)
