"""Resolve a bounded set of static imports from source bytes, without package loading."""

import ast
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath

from slop_measure.domain.architecture import (
    AnalyzedArchitectureFile,
    ArchitectureFile,
    ArchitecturePolicy,
    ExternalImport,
    FailedArchitectureFile,
    ImportEdge,
    ImportObservation,
    UnresolvedArchitectureFile,
    UnresolvedImport,
)
from slop_measure.domain.evidence import Diagnostic, DiagnosticSeverity
from slop_measure.domain.source import SourceDocument
from slop_measure.languages.python.rules._shared import bound_names, scope_nodes, span


@dataclass(frozen=True)
class _Module:
    document: SourceDocument
    name: str
    package: str


def _names(document: SourceDocument, roots: tuple[str, ...]) -> tuple[str, ...]:
    names = []
    for root in roots:
        path = PurePosixPath(document.path.root)
        if root != ".":
            try:
                path = path.relative_to(root)
            except ValueError:
                continue
        parts = path.with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        names.append(".".join(parts))
    return tuple(names)


def _index(
    documents: tuple[SourceDocument, ...], policy: ArchitecturePolicy
) -> tuple[list[_Module], list[ArchitectureFile], dict[str, list[_Module]]]:
    modules: list[_Module] = []
    files: list[ArchitectureFile] = []
    index: dict[str, list[_Module]] = defaultdict(list)
    for document in documents:
        names = _names(document, policy.source_roots)
        reason = None
        if not names:
            reason = "outside-source-roots"
        elif len(names) != 1:
            reason = "ambiguous-module"
        elif not all(part.isidentifier() for part in names[0].split(".")):
            reason = "invalid-module-path"
        if reason is not None:
            files.append(
                UnresolvedArchitectureFile(
                    path=document.path, source_sha256=document.content_hash, reason=reason
                )
            )
            continue
        name = names[0]
        package = name if document.path.root.endswith("/__init__.py") else name.rpartition(".")[0]
        module = _Module(document, name, package)
        modules.append(module)
        index[name].append(module)
        for count in range(1, len(name.split("."))):
            index.setdefault(".".join(name.split(".")[:count]), [])
    return modules, files, index


def _ambiguous(name: str, index: dict[str, list[_Module]]) -> bool:
    parts = name.split(".")
    for count in range(1, len(parts) + 1):
        prefix = ".".join(parts[:count])
        sources = index.get(prefix, [])
        if len(sources) > 1:
            return True
        if count < len(parts) and sources and sources[0].package != prefix:
            return True
    return False


def _package_members(index: dict[str, list[_Module]]) -> dict[str, frozenset[str]]:
    members = {}
    for name, sources in index.items():
        if len(sources) != 1 or sources[0].package != name:
            continue
        try:
            tree = ast.parse(sources[0].document.content)
        except (SyntaxError, ValueError, UnicodeError):
            members[name] = frozenset({"*"})
            continue
        names = {binding for node in scope_nodes(tree) for binding in bound_names(node)}
        if "__getattr__" in names or any(
            isinstance(node, ast.Name) and node.id in {"exec", "eval", "globals", "setattr"}
            for node in scope_nodes(tree)
        ):
            names.add("*")
        members[name] = frozenset(names)
    return members


def _unresolved(module: _Module, node: ast.stmt | ast.expr, reason) -> UnresolvedImport:
    return UnresolvedImport(
        importer=module.name,
        path=module.document.path,
        span=span(node),
        expression=ast.unparse(node),
        reason=reason,
    )


def _target(
    module: _Module, node: ast.stmt | ast.expr, target: str, index: dict[str, list[_Module]]
) -> ImportObservation:
    if _ambiguous(target, index):
        return _unresolved(module, node, "ambiguous-module")
    if target in index:
        return ImportEdge(
            importer=module.name,
            imported=target,
            path=module.document.path,
            span=span(node),
        )
    if target.split(".", maxsplit=1)[0] in index:
        return _unresolved(module, node, "missing-internal-module")
    return ExternalImport(
        importer=module.name, imported=target, path=module.document.path, span=span(node)
    )


def _from_import(
    module: _Module,
    node: ast.ImportFrom,
    index: dict[str, list[_Module]],
    package_members: dict[str, frozenset[str]],
) -> list[ImportObservation]:
    base = node.module or ""
    if node.level:
        package = module.package.split(".") if module.package else []
        if node.level > len(package):
            return [_unresolved(module, node, "relative-import-outside-package")]
        base = ".".join((*package[: len(package) - node.level + 1], *([base] if base else [])))
    result = []
    for alias in node.names:
        if alias.name == "*":
            result.append(_unresolved(module, node, "star-import"))
            continue
        child = f"{base}.{alias.name}"
        if {alias.name, "*"} & package_members.get(base, frozenset()):
            result.append(_target(module, node, base, index))
            result.append(_unresolved(module, node, "unresolved-package-member"))
        elif child in index:
            result.append(_target(module, node, child, index))
        elif base in index and not index[base]:
            result.append(_unresolved(module, node, "missing-internal-module"))
        elif base in index and index[base][0].package == base:
            result.append(_target(module, node, base, index))
            result.append(_unresolved(module, node, "unresolved-package-member"))
        else:
            result.append(_target(module, node, base, index))
    return result


def _dynamic_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    modules = {"importlib"}
    functions = {"__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(
                alias.asname or alias.name for alias in node.names if alias.name == "importlib"
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            functions.update(
                alias.asname or alias.name for alias in node.names if alias.name == "import_module"
            )
    return modules, functions


def _is_dynamic(node: ast.Call, modules: set[str], functions: set[str]) -> bool:
    return (isinstance(node.func, ast.Name) and node.func.id in functions) or (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "import_module"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in modules
    )


def _parse(
    module: _Module,
    index: dict[str, list[_Module]],
    package_members: dict[str, frozenset[str]],
) -> ArchitectureFile:
    try:
        tree = ast.parse(module.document.content, filename=module.document.path.root)
    except (SyntaxError, ValueError, UnicodeError) as error:
        return FailedArchitectureFile(
            path=module.document.path,
            diagnostic=Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="python.architecture-parse-error",
                message=str(error),
                path=module.document.path,
            ),
        )
    imports: list[ImportObservation] = []
    dynamic_modules, dynamic_functions = _dynamic_names(tree)
    for node in sorted(
        ast.walk(tree),
        key=lambda item: (getattr(item, "lineno", 0), getattr(item, "col_offset", 0)),
    ):
        if isinstance(node, ast.Import):
            imports.extend(_target(module, node, alias.name, index) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.extend(_from_import(module, node, index, package_members))
        elif isinstance(node, ast.Call) and _is_dynamic(node, dynamic_modules, dynamic_functions):
            imports.append(_unresolved(module, node, "dynamic-import"))
    return AnalyzedArchitectureFile(
        path=module.document.path,
        module=module.name,
        source_sha256=module.document.content_hash,
        imports=tuple(imports),
    )


def analyze_imports(
    documents: tuple[SourceDocument, ...], policy: ArchitecturePolicy
) -> tuple[ArchitectureFile, ...]:
    """Analyze only selected file paths; never consult Python's import machinery."""
    modules, files, index = _index(documents, policy)
    package_members = _package_members(index)
    for module in modules:
        if _ambiguous(module.name, index):
            files.append(
                UnresolvedArchitectureFile(
                    path=module.document.path,
                    source_sha256=module.document.content_hash,
                    reason="ambiguous-module",
                )
            )
        else:
            files.append(_parse(module, index, package_members))
    return tuple(sorted(files, key=lambda file: file.path.root))
