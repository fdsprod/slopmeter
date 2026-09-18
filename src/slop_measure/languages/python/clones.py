"""Extract complete executable runs with conservative local-name normalization."""

import ast
from collections.abc import Iterator, Mapping

from tree_sitter import Node

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import CloneCandidate, SourceSpan, clone_candidate_key
from slop_measure.languages.python.parsing import (
    NORMALIZATION_VERSION,
    parse_python,
    validate_tree,
    walk_nodes,
)
from slop_measure.languages.python.patterns import PythonParsedUnit

_Callable = ast.FunctionDef | ast.AsyncFunctionDef
_Position = tuple[int, int]
_SEPARATORS = frozenset(
    {
        "import_statement",
        "import_from_statement",
        "future_import_statement",
        "function_definition",
        "class_definition",
        "decorated_definition",
        "case_clause",
    }
)
_UNCERTAIN = (
    ast.Global,
    ast.Nonlocal,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.NamedExpr,
    ast.Import,
    ast.ImportFrom,
    ast.ExceptHandler,
    ast.Match,
)
_DYNAMIC_NAMES = frozenset({"exec", "eval", "locals", "globals", "vars"})
_TRIVIA = frozenset({"comment", "line_continuation"})


def _docstrings(tree: ast.Module) -> frozenset[_Position]:
    positions: set[_Position] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
        ):
            first = node.body[0]
            if isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                positions.add((first.lineno - 1, first.col_offset))
    return frozenset(positions)


def _uncertain(function: _Callable) -> bool:
    if function.type_params:
        return True
    for statement in function.body:
        for node in ast.walk(statement):
            if isinstance(node, (*_UNCERTAIN, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                return True
            if isinstance(node, ast.Name) and node.id in _DYNAMIC_NAMES:
                return True
    return False


def _function_names(function: _Callable) -> dict[str, str]:
    parameters = function.args
    args = [*parameters.posonlyargs, *parameters.args]
    if parameters.vararg is not None:
        args.append(parameters.vararg)
    args.extend(parameters.kwonlyargs)
    if parameters.kwarg is not None:
        args.append(parameters.kwarg)
    bindings = {argument.arg: f"parameter:{index}" for index, argument in enumerate(args)}
    stores = sorted(
        (
            node
            for statement in function.body
            for node in ast.walk(statement)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
        ),
        key=lambda node: (node.lineno, node.col_offset),
    )
    for node in stores:
        if node.id not in bindings:
            bindings[node.id] = f"local:{len(bindings) - len(args)}"
    return bindings


def _renamed_positions(tree: ast.Module) -> dict[_Position, str]:
    positions: dict[_Position, str] = {}
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) or _uncertain(
            function
        ):
            continue
        bindings = _function_names(function)
        for statement in function.body:
            for node in ast.walk(statement):
                if isinstance(node, ast.Name) and node.id in bindings:
                    positions[(node.lineno - 1, node.col_offset)] = bindings[node.id]
    return positions


def _runs(suite: Node, docstrings: frozenset[_Position]) -> Iterator[tuple[Node, ...]]:
    run: list[Node] = []
    for node in suite.named_children:
        if node.type in _TRIVIA:
            continue
        position = (node.start_point.row, node.start_point.column)
        if node.type in _SEPARATORS or position in docstrings:
            if run:
                yield tuple(run)
                run.clear()
        else:
            run.append(node)
    if run:
        yield tuple(run)


def _tokens(
    node: Node, source: bytes, names: Mapping[_Position, str], docstrings: frozenset[_Position]
) -> Iterator[str]:
    position = (node.start_point.row, node.start_point.column)
    if node.type in _TRIVIA or (node.type == "expression_statement" and position in docstrings):
        return
    yield f"begin:{node.type}"
    if node.type == "identifier":
        yield names.get(position, "name:" + source[node.start_byte : node.end_byte].decode("utf-8"))
    elif node.type == "string" or not node.children:
        # Literal spelling remains evidence, including quote style and f-string format syntax.
        yield "text:" + source[node.start_byte : node.end_byte].decode("utf-8")
    else:
        for child in node.children:
            yield from _tokens(child, source, names, docstrings)
    yield "end"


def extract_clone_candidates(
    unit: PythonParsedUnit, config: AnalysisConfig
) -> tuple[CloneCandidate, ...]:
    """Return deterministic complete runs that meet both configured minima."""
    source = unit.source.replace("\r\n", "\n").replace("\r", "\n")
    tree = parse_python(source)
    validate_tree(tree)
    encoded = source.encode("utf-8")
    names = _renamed_positions(unit.tree)
    docstrings = _docstrings(unit.tree)
    candidates: list[CloneCandidate] = []
    suites = (node for node in walk_nodes(tree.root_node) if node.type in {"module", "block"})
    for suite in suites:
        for run in _runs(suite, docstrings):
            start = run[0].start_point.row + 1
            last = run[-1].end_point
            end = last.row + bool(last.column)
            lines = tuple(line for line in unit.file.sloc_lines if start <= line <= end)
            if len(run) < config.clone_min_statements or len(lines) < config.clone_min_sloc:
                continue
            candidates.append(
                CloneCandidate(
                    path=unit.file.path,
                    span=SourceSpan(start_line=start, end_line=end),
                    statement_count=len(run),
                    sloc_lines=lines,
                    normalization_version=NORMALIZATION_VERSION,
                    normalized_tokens=tuple(
                        token for node in run for token in _tokens(node, encoded, names, docstrings)
                    ),
                )
            )
    unique = {clone_candidate_key(candidate): candidate for candidate in candidates}
    return tuple(unique[key] for key in sorted(unique))
