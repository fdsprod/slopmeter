"""Conservative straight-line proof of a stored local count read after mutation."""

import ast
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from slop_measure.domain.derived_review import (
    AnalyzedDerivedFile,
    AnalyzedDerivedFunction,
    DerivedFileResult,
    DerivedFunction,
    DerivedStateFinding,
    FailedDerivedFile,
    UnresolvedDerivedFunction,
)
from slop_measure.domain.evidence import Diagnostic, DiagnosticSeverity, SourceSpan
from slop_measure.domain.source import SourceDocument

_INSERT_ARITY = 2
_Function = ast.FunctionDef | ast.AsyncFunctionDef
_MutationKind = Literal["append", "extend", "insert"]


def _span(node: ast.stmt | ast.expr) -> SourceSpan:
    return SourceSpan(start_line=node.lineno, end_line=node.end_lineno or node.lineno)


def _literal(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple)):
        return all(_literal(item) for item in node.elts)
    return (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.UAdd, ast.USub))
        and isinstance(node.operand, ast.Constant)
        and type(node.operand.value) in (int, float, complex)
    )


class _Unresolved(Exception):
    """A proof boundary, not a source analysis failure."""


@dataclass(frozen=True)
class _Count:
    source: str
    derivation: SourceSpan
    mutation: tuple[SourceSpan, _MutationKind] | None = None


@dataclass
class _Trace:
    lists: set[str] = field(default_factory=set)
    scalars: set[str] = field(default_factory=set)
    counts: dict[str, _Count] = field(default_factory=dict)
    findings: list[DerivedStateFinding] = field(default_factory=list)

    def read(self, value: ast.expr, statement: ast.stmt) -> None:
        if isinstance(value, ast.Name):
            self._read_name(value.id, statement)
        elif isinstance(value, (ast.Tuple, ast.List)):
            for item in value.elts:
                self.read(item, statement)
        elif not _literal(value):
            raise _Unresolved("The read expression is outside the supported local scope.")

    def _read_name(self, name: str, statement: ast.stmt) -> None:
        if name not in self.scalars:
            raise _Unresolved("A value may alias a list or have an unknown local binding.")
        count = self.counts.get(name)
        if count is not None and count.mutation is not None:
            span, kind = count.mutation
            self.findings.append(
                DerivedStateFinding(
                    derived_name=name,
                    source_name=count.source,
                    derivation=count.derivation,
                    mutation=span,
                    mutation_kind=kind,
                    read=_span(statement),
                )
            )

    def assign(self, statement: ast.Assign) -> None:
        if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
            raise _Unresolved("Only a single local assignment target is supported.")
        name = statement.targets[0].id
        value = statement.value
        if name in self.lists:
            raise _Unresolved("A source list is rebound; its identity is no longer tracked.")
        if isinstance(value, ast.List) and _literal(value):
            self.counts.pop(name, None)
            self.scalars.discard(name)
            self.lists.add(name)
        elif isinstance(value, ast.Call):
            source = self._length_source(value)
            if source == name:
                raise _Unresolved("The stored count replaces the source binding.")
            self.scalars.add(name)
            self.counts[name] = _Count(source, _span(statement))
        else:
            self.read(value, statement)
            self.counts.pop(name, None)
            self.scalars.add(name)

    def _length_source(self, value: ast.Call) -> str:
        if (
            isinstance(value.func, ast.Name)
            and value.func.id == "len"
            and len(value.args) == 1
            and not value.keywords
            and isinstance(value.args[0], ast.Name)
            and value.args[0].id in self.lists
        ):
            return value.args[0].id
        raise _Unresolved("A call or length dependency is outside known local list literals.")

    def mutate(self, statement: ast.Expr) -> None:
        call = statement.value
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id in self.lists
            and not call.keywords
        ):
            raise _Unresolved("An unknown call or expression prevents a local mutation proof.")
        kind = _mutation_kind(call)
        if kind is None:
            return
        for name, count in tuple(self.counts.items()):
            if count.source == call.func.value.id and count.mutation is None:
                self.counts[name] = _Count(count.source, count.derivation, (_span(statement), kind))


def _mutation_kind(call: ast.Call) -> _MutationKind | None:
    if not isinstance(call.func, ast.Attribute):
        raise _Unresolved("A mutation must name a local list method.")
    args = call.args
    if call.func.attr == "append" and len(args) == 1 and _literal(args[0]):
        return "append"
    if (
        call.func.attr == "insert"
        and len(args) == _INSERT_ARITY
        and _literal(args[1])
        and isinstance(args[0], ast.Constant)
        and type(args[0].value) is int
    ):
        return "insert"
    if (
        call.func.attr == "extend"
        and len(args) == 1
        and isinstance(args[0], ast.List)
        and _literal(args[0])
    ):
        return "extend" if args[0].elts else None
    raise _Unresolved("The mutation or its arguments cannot establish a length increase.")


def _trace(function: ast.FunctionDef) -> tuple[DerivedStateFinding, ...]:
    state = _Trace()
    for statement in function.body:
        if isinstance(statement, ast.Assign):
            state.assign(statement)
        elif isinstance(statement, ast.Return):
            if statement.value is not None:
                state.read(statement.value, statement)
            break
        elif isinstance(statement, ast.Expr):
            if not isinstance(statement.value, ast.Constant):
                state.mutate(statement)
        elif not isinstance(statement, ast.Pass):
            raise _Unresolved(
                "Control flow or another statement lies outside straight-line analysis."
            )
    return tuple(dict.fromkeys(state.findings))


class _BuiltinBinding(ast.NodeVisitor):
    """Locate explicit builtin shadowing without treating other function locals as globals."""

    def __init__(self) -> None:
        self.uncertain = False

    def visit_Name(self, node: ast.Name) -> None:
        self.uncertain |= node.id in {"len", "__builtins__"} and isinstance(
            node.ctx, (ast.Store, ast.Del)
        )

    def visit_arg(self, node: ast.arg) -> None:
        self.uncertain |= node.arg == "len"
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self.uncertain |= any((a.asname or a.name.split(".")[0]) == "len" for a in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.uncertain |= any((a.asname or a.name) in {"len", "*"} for a in node.names)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.uncertain |= node.name == "len"
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        self.uncertain |= node.name == "len"
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        self.uncertain |= node.name == "len"

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        self.uncertain |= node.rest == "len"
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.uncertain |= node.attr == "len" and isinstance(node.ctx, (ast.Store, ast.Del))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: _Function) -> None:
        self.uncertain |= node.name == "len"
        for expression in (*node.decorator_list, *node.args.defaults, *node.args.kw_defaults):
            if expression is not None:
                self.visit(expression)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.uncertain |= node.name == "len"
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        self.uncertain |= isinstance(node.func, ast.Name) and node.func.id in {
            "exec",
            "eval",
            "globals",
            "locals",
            "vars",
            "setattr",
            "delattr",
        }
        self.generic_visit(node)


def _assess(function: _Function, *, supported: bool, builtin_known: bool) -> DerivedFunction:
    try:
        if (
            not supported
            or not isinstance(function, ast.FunctionDef)
            or function.decorator_list
            or function.type_params
        ):
            raise _Unresolved("Only undecorated top-level synchronous functions are supported.")
        bindings = _BuiltinBinding()
        bindings.visit(function.args)
        for statement in function.body:
            bindings.visit(statement)
        if not builtin_known or bindings.uncertain:
            raise _Unresolved("The builtin len binding is shadowed or uncertain.")
        return AnalyzedDerivedFunction(
            symbol=function.name,
            span=_span(function),
            findings=_trace(function),
        )
    except _Unresolved as error:
        return UnresolvedDerivedFunction(
            symbol=function.name,
            span=_span(function),
            reason=str(error),
        )


def analyze_derived(document: SourceDocument) -> DerivedFileResult:
    """Parse source without executing it and retain every function's analysis state."""
    if document.language != "python":
        raise ValueError("Python derived review requires Python source")
    try:
        tree = ast.parse(document.content, filename=document.path.root)
    except (SyntaxError, UnicodeError, ValueError) as error:
        return FailedDerivedFile(
            path=document.path,
            cohort=document.cohort,
            source_sha256=document.content_hash,
            diagnostic=Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="python.derived-review-parse-error",
                message=str(error),
                path=document.path,
            ),
        )
    bindings = _BuiltinBinding()
    bindings.visit(tree)
    names = Counter(node.name for node in tree.body if isinstance(node, _Function))
    functions = sorted(
        (node for node in ast.walk(tree) if isinstance(node, _Function)),
        key=lambda node: (node.lineno, node.col_offset),
    )
    return AnalyzedDerivedFile(
        path=document.path,
        cohort=document.cohort,
        source_sha256=document.content_hash,
        functions=tuple(
            _assess(
                node,
                supported=node in tree.body and names[node.name] == 1,
                builtin_known=not bindings.uncertain,
            )
            for node in functions
        ),
    )
