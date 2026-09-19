"""Source-only review of first-match handlers for finite local Python variants."""

import ast
from collections import Counter
from dataclasses import dataclass

from slop_measure.domain.evidence import Diagnostic, DiagnosticSeverity, SourceSpan
from slop_measure.domain.source import SourceDocument
from slop_measure.domain.variant_review import (
    AnalyzedVariantFile,
    AnalyzedVariantHandler,
    ExplicitVariantBranch,
    FailedVariantFile,
    FallbackVariantBranch,
    UnresolvedVariantHandler,
    VariantBranch,
    VariantCase,
    VariantDeclaration,
    VariantFileResult,
    VariantHandler,
)

_Function = ast.FunctionDef | ast.AsyncFunctionDef


def _all_arguments(function: _Function) -> tuple[ast.arg, ...]:
    args = function.args
    return (
        *args.posonlyargs,
        *args.args,
        *args.kwonlyargs,
        *((args.vararg,) if args.vararg else ()),
        *((args.kwarg,) if args.kwarg else ()),
    )


def _span(node: ast.stmt | ast.expr | ast.pattern) -> SourceSpan:
    return SourceSpan(start_line=node.lineno, end_line=node.end_lineno or node.lineno)


class _Bindings(ast.NodeVisitor):
    """Collect scope bindings, including captures and evaluated definition expressions."""

    def __init__(self) -> None:
        self.names: Counter[str] = Counter()
        self.uncertain = False

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names[node.id] += 1

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)) and isinstance(node.value, ast.Name):
            self.names[node.value.id] += 1
        self.generic_visit(node)

    def visit_FunctionDef(self, node: _Function) -> None:
        self.names[node.name] += 1
        expressions = (
            *node.decorator_list,
            *node.args.defaults,
            *node.args.kw_defaults,
            *(argument.annotation for argument in _all_arguments(node)),
            node.returns,
        )
        for expression in expressions:
            if expression is not None:
                self.visit(expression)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names[node.name] += 1
        for expression in (*node.decorator_list, *node.bases):
            self.visit(expression)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for expression in (*node.args.defaults, *node.args.kw_defaults):
            if expression is not None:
                self.visit(expression)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.names[alias.asname or alias.name.split(".")[0]] += 1

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.names[alias.asname or alias.name] += 1
            self.uncertain |= alias.name == "*"

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.names[node.name] += 1
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name:
            self.names[node.name] += 1
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name:
            self.names[node.name] += 1

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest:
            self.names[node.rest] += 1
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.uncertain = True

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.uncertain = True

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in {
            "exec",
            "eval",
            "setattr",
            "delattr",
        }:
            self.uncertain = True
        self.generic_visit(node)


def _bindings(statements: list[ast.stmt]) -> _Bindings:
    result = _Bindings()
    for statement in statements:
        result.visit(statement)
    return result


def _imports(tree: ast.Module, bindings: _Bindings) -> dict[str, tuple[str, str]]:
    return {
        alias.asname or alias.name: (statement.module, alias.name)
        for statement in tree.body
        if isinstance(statement, ast.ImportFrom)
        and statement.level == 0
        and statement.module in {"enum", "typing"}
        for alias in statement.names
        if bindings.names[alias.asname or alias.name] == 1
    }


def _constant(node: ast.expr) -> str | int | None:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (str, int))
        and not isinstance(node.value, bool)
    ):
        return node.value
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and type(node.operand.value) is int
    ):
        return -node.operand.value
    return None


def _docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _enum_members(
    node: ast.ClassDef, base: str, imports: dict[str, tuple[str, str]]
) -> tuple[VariantCase, ...] | None:
    members: list[VariantCase] = []
    values: list[str | int] = []
    modes: set[str] = set()
    local = _bindings(node.body)
    for statement in node.body:
        if _docstring(statement):
            continue
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            return None
        target = statement.targets[0]
        if (
            not isinstance(target, ast.Name)
            or target.id.startswith("_")
            or local.names[target.id] != 1
        ):
            return None
        value = _enum_value(statement.value, target.id, base, imports, local)
        if value is None:
            return None
        mode, resolved = value
        modes.add(mode)
        values.append(resolved)
        members.append(VariantCase(name=f"{node.name}.{target.id}", span=_span(statement)))
    if len(modes) != 1 or len(set(values)) != len(values):
        return None
    return tuple(members) or None


def _enum_value(
    expression: ast.expr,
    name: str,
    base: str,
    imports: dict[str, tuple[str, str]],
    local: _Bindings,
) -> tuple[str, str | int] | None:
    if isinstance(expression, ast.Call) and isinstance(expression.func, ast.Name):
        if (
            not expression.args
            and not expression.keywords
            and imports.get(expression.func.id) == ("enum", "auto")
            and not local.names[expression.func.id]
        ):
            return "auto", name.lower() if base == "StrEnum" else name
        return None
    value = _constant(expression)
    if (
        value is None
        or (base == "IntEnum" and type(value) is not int)
        or (base == "StrEnum" and type(value) is not str)
    ):
        return None
    return "literal", value


def _enum_declaration(
    node: ast.ClassDef, imports: dict[str, tuple[str, str]]
) -> VariantDeclaration | None:
    if node.decorator_list or node.keywords or node.type_params or len(node.bases) != 1:
        return None
    base_node = node.bases[0]
    origin = imports.get(base_node.id) if isinstance(base_node, ast.Name) else None
    if origin not in {("enum", "Enum"), ("enum", "IntEnum"), ("enum", "StrEnum")}:
        return None
    cases = _enum_members(node, origin[1], imports)
    return (
        VariantDeclaration(name=node.name, kind="enum", span=_span(node), cases=cases)
        if cases
        else None
    )


def _alias_parts(
    node: ast.stmt, imports: dict[str, tuple[str, str]]
) -> tuple[str, ast.expr] | None:
    if (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ):
        return node.targets[0].id, node.value
    if (
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.value is not None
        and isinstance(node.annotation, ast.Name)
        and imports.get(node.annotation.id) == ("typing", "TypeAlias")
    ):
        return node.target.id, node.value
    if isinstance(node, ast.TypeAlias) and not node.type_params:
        return node.name.id, node.value
    return None


def _literal_declaration(
    node: ast.stmt, imports: dict[str, tuple[str, str]]
) -> VariantDeclaration | None:
    parts = _alias_parts(node, imports)
    if parts is None:
        return None
    name, expression = parts
    if not isinstance(expression, ast.Subscript) or not isinstance(expression.value, ast.Name):
        return None
    if imports.get(expression.value.id) != ("typing", "Literal"):
        return None
    elements = (
        expression.slice.elts if isinstance(expression.slice, ast.Tuple) else [expression.slice]
    )
    values = [_constant(element) for element in elements]
    if not values or None in values or len(set(values)) != len(values):
        return None
    return VariantDeclaration(
        name=name,
        kind="literal",
        span=_span(node),
        cases=tuple(
            VariantCase(name=repr(value), span=_span(element))
            for value, element in zip(values, elements, strict=True)
        ),
    )


@dataclass(frozen=True)
class _MatchOwner:
    match: ast.Match
    function: _Function | None
    symbol: str
    top_level: bool


class _Matches(ast.NodeVisitor):
    def __init__(self, tree: ast.Module) -> None:
        self.top_functions = {
            node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.scopes: list[ast.ClassDef | _Function] = []
        self.matches: list[_MatchOwner] = []

    def visit_FunctionDef(self, node: _Function) -> None:
        self.scopes.append(node)
        for statement in node.body:
            self.visit(statement)
        self.scopes.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scopes.append(node)
        for statement in node.body:
            self.visit(statement)
        self.scopes.pop()

    def visit_Match(self, node: ast.Match) -> None:
        owner = self.scopes[-1] if self.scopes else None
        function = owner if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)) else None
        self.matches.append(
            _MatchOwner(
                node,
                function,
                ".".join(scope.name for scope in self.scopes) or "<module>",
                len(self.scopes) == 1 and function in self.top_functions,
            )
        )
        self.generic_visit(node)


def _annotation_name(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _handler_type(owner: _MatchOwner, bindings: _Bindings) -> str | None:
    function = owner.function
    if not owner.top_level or function is None or function.decorator_list or function.type_params:
        return None
    body = function.body[1:] if function.body and _docstring(function.body[0]) else function.body
    if not body or body[0] is not owner.match or not isinstance(owner.match.subject, ast.Name):
        return None
    if bindings.uncertain or bindings.names[function.name] != 1:
        return None
    subject = owner.match.subject.id
    args = (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
    argument = next((arg for arg in args if arg.arg == subject), None)
    name = _annotation_name(argument.annotation) if argument else None
    local = _bindings(function.body)
    if name is None or local.uncertain or local.names[name] or local.names[subject]:
        return None
    if any(arg.arg == name for arg in _all_arguments(function)):
        return None
    return name


def _pattern_cases(pattern: ast.pattern, declaration: VariantDeclaration) -> tuple[str, ...] | None:
    if isinstance(pattern, ast.MatchOr):
        parts = [_pattern_cases(part, declaration) for part in pattern.patterns]
        if any(part is None for part in parts):
            return None
        return tuple(dict.fromkeys(name for part in parts if part is not None for name in part))
    if not isinstance(pattern, ast.MatchValue):
        return None
    value = pattern.value
    if declaration.kind == "enum":
        if not isinstance(value, ast.Attribute) or not isinstance(value.value, ast.Name):
            return None
        name = f"{value.value.id}.{value.attr}"
    else:
        constant = _constant(value)
        if constant is None:
            return None
        name = repr(constant)
    return (name,) if name in {case.name for case in declaration.cases} else None


def _branches(
    match: ast.Match, declaration: VariantDeclaration
) -> tuple[VariantBranch, ...] | None:
    branches: list[VariantBranch] = []
    for index, case in enumerate(match.cases):
        pattern = case.pattern
        if isinstance(pattern, ast.MatchAs) and pattern.pattern is None:
            if case.guard is None and index != len(match.cases) - 1:
                return None
            branches.append(
                FallbackVariantBranch(span=_span(pattern), conditional=case.guard is not None)
            )
        else:
            cases = _pattern_cases(pattern, declaration)
            if not cases:
                return None
            branches.append(
                ExplicitVariantBranch(
                    span=_span(pattern), cases=cases, conditional=case.guard is not None
                )
            )
    return tuple(branches)


def _assess(
    owner: _MatchOwner, bindings: _Bindings, declarations: dict[str, VariantDeclaration]
) -> VariantHandler:
    name = _handler_type(owner, bindings)
    declaration = declarations.get(name) if name else None
    branches = _branches(owner.match, declaration) if declaration is not None else None
    subject = ast.unparse(owner.match.subject)
    span = _span(owner.match)
    if declaration is None or branches is None:
        return UnresolvedVariantHandler(
            symbol=owner.symbol,
            subject=subject,
            span=span,
            reason="The local declaration, subject binding, or match pattern is outside "
            "the supported finite scope.",
        )
    return AnalyzedVariantHandler(
        symbol=owner.symbol, subject=subject, span=span, declaration=declaration, branches=branches
    )


def analyze_variants(document: SourceDocument) -> VariantFileResult:
    """Inspect finite local declarations and matches without executing target code."""
    if document.language != "python":
        raise ValueError("Python variant review requires Python source")
    try:
        tree = ast.parse(document.content, filename=document.path.root)
    except (SyntaxError, UnicodeError, ValueError) as error:
        return FailedVariantFile(
            path=document.path,
            cohort=document.cohort,
            source_sha256=document.content_hash,
            diagnostic=Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="python.variant-review-parse-error",
                message=str(error),
                path=document.path,
            ),
        )
    bindings = _bindings(tree.body)
    imports = _imports(tree, bindings)
    declarations: dict[str, VariantDeclaration] = {}
    for node in tree.body:
        declaration = (
            _enum_declaration(node, imports)
            if isinstance(node, ast.ClassDef)
            else _literal_declaration(node, imports)
        )
        if declaration is not None and bindings.names[declaration.name] == 1:
            declarations[declaration.name] = declaration
    matches = _Matches(tree)
    matches.visit(tree)
    return AnalyzedVariantFile(
        path=document.path,
        cohort=document.cohort,
        source_sha256=document.content_hash,
        handlers=tuple(
            _assess(owner, bindings, declarations)
            for owner in sorted(matches.matches, key=lambda item: item.match.lineno)
        ),
    )
