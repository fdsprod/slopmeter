"""Local AST and token facts shared by the built-in review rules."""

import ast
import tokenize
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from slop_measure.domain.evidence import PatternCategory, PatternFinding, SourceSpan
from slop_measure.languages.python.patterns import (
    PythonParsedUnit,
    PythonProjectContext,
    RuleMetadata,
)

type Detector = Callable[[PythonParsedUnit], Iterable[SourceSpan]]
type Function = ast.FunctionDef | ast.AsyncFunctionDef
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_DYNAMIC = frozenset({"exec", "eval", "locals", "globals"})


@dataclass(frozen=True)
class Rule:
    """Attach one immutable rule identity to detected source spans."""

    metadata: RuleMetadata
    detect: Detector

    def analyze(
        self, unit: PythonParsedUnit, context: PythonProjectContext
    ) -> tuple[PatternFinding, ...]:
        return tuple(
            PatternFinding(path=unit.file.path, span=span, **self.metadata.model_dump())
            for span in self.detect(unit)
        )


def rule(
    name: str,
    category: PatternCategory,
    message: str,
    detect: Detector,
    *,
    remediation: str | None = None,
) -> Rule:
    return Rule(
        RuleMetadata(
            rule_id=f"py.{name}", category=category, message=message, remediation=remediation
        ),
        detect,
    )


def span(node: ast.stmt | ast.expr | ast.keyword) -> SourceSpan:
    return SourceSpan(start_line=node.lineno, end_line=node.end_lineno or node.lineno)


def bound_names(node: ast.AST) -> tuple[str, ...]:
    match node:
        case (
            ast.Name(id=name, ctx=ast.Store() | ast.Del())
            | ast.arg(arg=name)
            | ast.FunctionDef(name=name)
            | ast.AsyncFunctionDef(name=name)
            | ast.ClassDef(name=name)
            | ast.TypeVar(name=name)
            | ast.ParamSpec(name=name)
            | ast.TypeVarTuple(name=name)
        ):
            return (name,)
        case ast.Import(names=names):
            return tuple(alias.asname or alias.name.split(".")[0] for alias in names)
        case ast.ImportFrom(names=names):
            return tuple(alias.asname or alias.name for alias in names)
        case ast.ExceptHandler(name=name) | ast.MatchAs(name=name) | ast.MatchStar(name=name):
            return (name,) if name else ()
        case ast.MatchMapping(rest=name):
            return (name,) if name else ()
        case _:
            return ()


def builtin_available(tree: ast.Module, name: str) -> bool:
    for node in ast.walk(tree):
        bindings = bound_names(node)
        if name in bindings or "*" in bindings:
            return False
        if isinstance(node, ast.Name) and node.id in {"exec", "eval"}:
            return False
    return True


def scope_nodes(scope: ast.AST) -> Iterator[ast.AST]:
    """Visit one scope, keeping nested definitions but excluding their bodies."""
    yield scope
    for child in ast.iter_child_nodes(scope):
        if isinstance(child, (*_SCOPES, *_COMPREHENSIONS)):
            yield child
        else:
            yield from scope_nodes(child)


class ScopeIndex:
    """A per-rule parent index derived from the unchanged source AST."""

    def __init__(self, tree: ast.Module) -> None:
        self.parents = {
            child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
        }

    def function(self, node: ast.AST) -> Function | None:
        parent = self.parents.get(node)
        while parent is not None:
            if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef):
                return parent
            if isinstance(parent, ast.ClassDef | ast.Lambda):
                return None
            parent = self.parents.get(parent)
        return None

    def stable_local(self, node: ast.AST, name: str) -> Function | None:
        owner = self.function(node)
        if owner is None:
            return None
        nodes = tuple(scope_nodes(owner))
        if any(
            isinstance(item, ast.Global | ast.Nonlocal) and name in item.names for item in nodes
        ):
            return None
        if not any(name in bound_names(item) for item in nodes if item is not owner):
            return None
        if any(isinstance(item, ast.Name) and item.id in _DYNAMIC for item in ast.walk(owner)):
            return None
        for nested in nodes:
            if (
                nested is not owner
                and isinstance(nested, (*_SCOPES, *_COMPREHENSIONS))
                and any(isinstance(item, ast.Name) and item.id == name for item in ast.walk(nested))
            ):
                return None
        return owner


def unique_use(owner: Function, name: str) -> bool:
    nodes = tuple(scope_nodes(owner))
    return (
        sum(name in bound_names(node) for node in nodes if node is not owner) == 1
        and sum(
            isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load)
            for node in ast.walk(owner)
        )
        == 1
    )


def suites(tree: ast.AST) -> Iterator[list[ast.stmt]]:
    for node in ast.walk(tree):
        for _, value in ast.iter_fields(node):
            if (
                isinstance(value, list)
                and value
                and all(isinstance(item, ast.stmt) for item in value)
            ):
                yield value


def tokens(unit: PythonParsedUnit) -> tuple[tokenize.TokenInfo, ...]:
    return unit.token_stream


def has_type_comment(unit: PythonParsedUnit, node: ast.stmt) -> bool:
    """Preserve source annotations omitted by the shared AST parser settings."""
    location = span(node)
    return any(
        token.type == tokenize.COMMENT
        and location.start_line <= token.start[0] <= location.end_line
        and ":" in token.string
        and token.string.partition(":")[0].removeprefix("#").strip() == "type"
        for token in tokens(unit)
    )


def header(
    unit: PythonParsedUnit, keyword: str, start: int, end: int, column: int
) -> SourceSpan | None:
    """Find a suite keyword at its actual indentation, then its colon."""
    stream = iter(tokens(unit))
    first = next(
        (
            token
            for token in stream
            if token.type == tokenize.NAME
            and token.string == keyword
            and start <= token.start[0] <= end
            and token.start[1] == column
        ),
        None,
    )
    if first is None:
        return None
    depth = 0
    for token in stream:
        if token.type != tokenize.OP:
            continue
        if token.string in {"(", "[", "{"}:
            depth += 1
        elif token.string in {")", "]", "}"}:
            depth -= 1
        elif token.string == ":" and depth == 0:
            return SourceSpan(start_line=first.start[0], end_line=token.end[0])
    return None


def if_header(unit: PythonParsedUnit, node: ast.If) -> SourceSpan | None:
    found = header(unit, "if", node.lineno, node.lineno, node.col_offset)
    if found is None:
        return None
    # A lambda's colon can precede the suite colon. The AST test end disambiguates it.
    lines = unit.source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    end_line = node.test.end_lineno or node.test.lineno
    end_column = len(
        lines[end_line - 1].encode("utf-8")[: node.test.end_col_offset].decode("utf-8")
    )
    colon = next(
        token
        for token in tokens(unit)
        if token.type == tokenize.OP
        and token.string == ":"
        and token.start >= (end_line, end_column)
    )
    return SourceSpan(start_line=node.lineno, end_line=colon.end[0])


def is_none(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def none_test(node: ast.AST, operator: type[ast.cmpop]) -> str | None:
    if (
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and len(node.ops) == len(node.comparators) == 1
        and isinstance(node.ops[0], operator)
        and is_none(node.comparators[0])
    ):
        return node.left.id
    return None
