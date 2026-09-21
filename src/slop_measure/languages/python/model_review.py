"""Conservative same-file evidence for repeated dataclass rejection guards."""

import ast
from collections import Counter
from typing import Literal

from slop_measure.domain.evidence import Diagnostic, DiagnosticSeverity, SourceSpan
from slop_measure.domain.model_review import (
    AnalyzedModel,
    AnalyzedModelFile,
    CoupledStateFinding,
    FailedModelFile,
    GuardLocation,
    ModelAssessment,
    ModelField,
    ModelFileResult,
    UnresolvedModel,
)
from slop_measure.domain.source import SourceDocument

_MIN_CONSUMERS = 2


class _Bindings(ast.NodeVisitor):
    """Count bindings in one scope, without entering callable or class bodies."""

    def __init__(self) -> None:
        self.names: Counter[str] = Counter()
        self.uncertain = False

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names[node.id] += 1

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.names[node.name] += 1
        for expression in (*node.decorator_list, *node.args.defaults, *node.args.kw_defaults):
            if expression is not None:
                self.visit(expression)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names[node.name] += 1

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

    def visit_Match(self, node: ast.Match) -> None:
        self.uncertain = True

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in {"exec", "eval"}:
            self.uncertain = True
        self.generic_visit(node)


def _span(node: ast.stmt | ast.expr) -> SourceSpan:
    return SourceSpan(start_line=node.lineno, end_line=node.end_lineno or node.lineno)


def _field_kind(node: ast.expr) -> Literal["boolean", "nullable"] | None:
    if isinstance(node, ast.Name) and node.id == "bool":
        return "boolean"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        sides = (node.left, node.right)
        if any(isinstance(side, ast.Constant) and side.value is None for side in sides):
            other = (
                next(side for side in sides if not isinstance(side, ast.Constant))
                if any(not isinstance(side, ast.Constant) for side in sides)
                else None
            )
            if isinstance(other, (ast.Name, ast.Attribute, ast.Subscript)):
                return "nullable"
    return None


def _fields(model: ast.ClassDef) -> tuple[ModelField, ...] | None:
    bindings = _Bindings()
    for statement in model.body:
        bindings.visit(statement)
    fields: list[ModelField] = []
    for statement in model.body:
        if not isinstance(statement, ast.AnnAssign):
            continue
        kind = _field_kind(statement.annotation)
        if (
            not isinstance(statement.target, ast.Name)
            or kind is None
            or (kind == "boolean" and bindings.names["bool"])
            or bindings.names[statement.target.id] != 1
        ):
            return None
        fields.append(ModelField(name=statement.target.id, kind=kind, span=_span(statement)))
    if len({field.name for field in fields}) != len(fields):
        return None
    return tuple(fields)


def _attribute(node: ast.expr, receiver: str) -> str | None:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == receiver
    ):
        return node.attr
    return None


def _predicate(node: ast.expr, receiver: str, fields: dict[str, ModelField]) -> ast.expr | None:
    name = _attribute(node, receiver)
    if name in fields and fields[name].kind == "boolean":
        return ast.Attribute(value=ast.Name(id="model", ctx=ast.Load()), attr=name, ctx=ast.Load())
    if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        values = [_predicate(value, receiver, fields) for value in node.values]
        if all(value is not None for value in values):
            return ast.BoolOp(op=node.op, values=[value for value in values if value is not None])
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        operand = _predicate(node.operand, receiver, fields)
        if operand is not None:
            return ast.UnaryOp(op=node.op, operand=operand)
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        name = _attribute(node.left, receiver)
        right = node.comparators[0]
        if (
            name in fields
            and fields[name].kind == "nullable"
            and isinstance(node.ops[0], (ast.Is, ast.IsNot))
            and isinstance(right, ast.Constant)
            and right.value is None
        ):
            return ast.Compare(
                left=ast.Attribute(
                    value=ast.Name(id="model", ctx=ast.Load()), attr=name, ctx=ast.Load()
                ),
                ops=node.ops,
                comparators=[ast.Constant(value=None)],
            )
    return None


def _arguments(function: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[ast.arg, ...]:
    args = function.args
    return (*args.posonlyargs, *args.args, *args.kwonlyargs)


def _first_guard(function: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.If | None:
    """Stop before calls, assignments, or control flow can change incoming state."""
    for statement in function.body:
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            continue
        return statement if isinstance(statement, ast.If) else None
    return None


def _safe_function(function: ast.FunctionDef | ast.AsyncFunctionDef, receiver: str) -> bool:
    if function.decorator_list or function.type_params:
        return False
    for statement in function.body:
        for node in ast.walk(statement):
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                    ast.Lambda,
                    ast.Global,
                    ast.Nonlocal,
                ),
            ):
                return False
            if (
                isinstance(node, ast.Name)
                and node.id == receiver
                and isinstance(node.ctx, (ast.Store, ast.Del))
            ):
                return False
    return True


def _annotation_name(annotation: ast.expr | None) -> str | None:
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return annotation.value
    return None


def _consumer_guard(
    function: ast.FunctionDef | ast.AsyncFunctionDef, model_name: str
) -> ast.If | None:
    local = _Bindings()
    for statement in function.body:
        local.visit(statement)
    if local.uncertain or local.names[model_name]:
        return None
    if any(arg.arg == model_name for arg in _arguments(function)):
        return None
    return _first_guard(function)


def _consumers(
    tree: ast.Module,
    model: ast.ClassDef,
    fields: dict[str, ModelField],
    predicate: str,
    bindings: _Bindings,
) -> tuple[GuardLocation, ...]:
    found: list[GuardLocation] = []
    for function in tree.body:
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if bindings.names[function.name] != 1:
            continue
        guard = _consumer_guard(function, model.name)
        if guard is None:
            continue
        for arg in _arguments(function):
            if _annotation_name(arg.annotation) != model.name or not _safe_function(
                function, arg.arg
            ):
                continue
            normalized = _predicate(guard.test, arg.arg, fields)
            if normalized is not None and ast.unparse(normalized) == predicate:
                found.append(GuardLocation(symbol=function.name, span=_span(guard.test)))
                break
    return tuple(found)


def _validator_guard(model: ast.ClassDef) -> tuple[ast.If, str] | None:
    validators = [
        node
        for node in model.body
        if isinstance(node, ast.FunctionDef) and node.name == "__post_init__"
    ]
    if len(validators) != 1:
        return None
    validator = validators[0]
    arguments = _arguments(validator)
    if not arguments or not _safe_function(validator, arguments[0].arg):
        return None
    guard = _first_guard(validator)
    if guard is None or len(guard.body) != 1 or not isinstance(guard.body[0], ast.Raise):
        return None
    return guard, arguments[0].arg


def _findings(
    tree: ast.Module, model: ast.ClassDef, fields: tuple[ModelField, ...], bindings: _Bindings
) -> tuple[CoupledStateFinding, ...]:
    validator = _validator_guard(model)
    if validator is None:
        return ()
    guard, receiver = validator
    by_name = {field.name: field for field in fields}
    normalized = _predicate(guard.test, receiver, by_name)
    if normalized is None:
        return ()
    names = {node.attr for node in ast.walk(normalized) if isinstance(node, ast.Attribute)}
    used = tuple(field for field in fields if field.name in names)
    if {field.kind for field in used} != {"boolean", "nullable"}:
        return ()
    predicate = ast.unparse(normalized)
    consumers = _consumers(tree, model, by_name, predicate, bindings)
    if len(consumers) < _MIN_CONSUMERS:
        return ()
    return (
        CoupledStateFinding(
            fields=used,
            predicate=predicate,
            validator=GuardLocation(symbol=f"{model.name}.__post_init__", span=_span(guard.test)),
            consumers=consumers,
        ),
    )


def _model_reason(model: ast.ClassDef, tree: ast.Module, bindings: _Bindings) -> str | None:
    if model not in tree.body or model.bases or model.keywords or model.type_params:
        return "Nested, inherited, or parameterized model declarations are not supported."
    if bindings.uncertain or bindings.names[model.name] != 1 or bindings.names["bool"]:
        return "Model or annotation bindings are ambiguous."
    if reason := _construction_reason(model):
        return reason
    aliases = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "dataclasses" and node.level == 0
        for alias in node.names
        if alias.name == "dataclass"
    }
    decorators = [
        item.func if isinstance(item, ast.Call) else item for item in model.decorator_list
    ]
    if len(decorators) != 1 or not isinstance(decorators[0], ast.Name):
        return "Only directly imported dataclass decorators are supported."
    name = decorators[0].id
    if name not in aliases or bindings.names[name] != 1:
        return "The dataclass decorator is unresolved or shadowed."
    return None


def _construction_reason(model: ast.ClassDef) -> str | None:
    bindings = _Bindings()
    for statement in model.body:
        bindings.visit(statement)
    if bindings.names["__init__"] or bindings.names["__post_init__"] > 1:
        return "Custom construction or a replaced post-init hook is not supported."
    for decorator in model.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if decorator.args or any(keyword.arg is None for keyword in decorator.keywords):
            return "Dataclass constructor options are unresolved."
        for keyword in decorator.keywords:
            if keyword.arg == "init" and not (
                isinstance(keyword.value, ast.Constant) and keyword.value.value is True
            ):
                return "Dataclass-generated initialization is not established."
    return None


def _assess(tree: ast.Module, model: ast.ClassDef, bindings: _Bindings) -> ModelAssessment:
    reason = _model_reason(model, tree, bindings)
    fields = _fields(model)
    if reason is not None or fields is None:
        return UnresolvedModel(
            name=model.name,
            span=_span(model),
            reason=reason
            or "Field annotations are outside the supported boolean and nullable forms.",
        )
    return AnalyzedModel(
        name=model.name, span=_span(model), findings=_findings(tree, model, fields, bindings)
    )


def analyze_models(document: SourceDocument) -> ModelFileResult:
    """Parse source bytes without executing a module, validator, or consumer."""
    if document.language != "python":
        raise ValueError("Python model review requires a Python source document")
    try:
        tree = ast.parse(document.content, filename=document.path.root)
    except (SyntaxError, UnicodeError, ValueError) as error:
        return FailedModelFile(
            path=document.path,
            cohort=document.cohort,
            source_sha256=document.content_hash,
            diagnostic=Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="python.model-review-parse-error",
                message=str(error),
                path=document.path,
            ),
        )
    bindings = _Bindings()
    bindings.visit(tree)
    models = sorted(
        (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)),
        key=lambda node: node.lineno,
    )
    return AnalyzedModelFile(
        path=document.path,
        cohort=document.cohort,
        source_sha256=document.content_hash,
        models=tuple(_assess(tree, model, bindings) for model in models),
    )
