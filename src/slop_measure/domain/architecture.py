"""Source-bound import observations and declared direct dependency policy."""

from collections.abc import Mapping
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    StringConstraints,
    computed_field,
    field_validator,
    model_validator,
)

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import Coverage, Diagnostic, ExcludedDirectory, SourceSpan
from slop_measure.domain.source import ProjectPath, SourceIdentity

_Text = Annotated[str, StringConstraints(min_length=1)]
_Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class _ArchitectureEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ForbiddenDependency(_ArchitectureEvidence):
    source: _Text
    target: _Text

    @field_validator("source", "target")
    @classmethod
    def module_name(cls, value: str) -> str:
        if not all(part.isidentifier() for part in value.split(".")):
            raise ValueError("architecture boundaries require dotted module names")
        return value


class ArchitecturePolicy(_ArchitectureEvidence):
    source_roots: Annotated[tuple[str, ...], Field(min_length=1)] = (".",)
    forbidden: tuple[ForbiddenDependency, ...] = ()

    @field_validator("source_roots")
    @classmethod
    def relative_roots(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple("." if value == "." else ProjectPath(value).root for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("architecture source roots must be unique")
        return normalized


class ImportContext(_ArchitectureEvidence):
    execution: Literal["eager", "deferred", "unknown"] = "unknown"
    guards: tuple[Literal["type-checking", "conditional"], ...] = ()

    @model_validator(mode="after")
    def distinct_guards(self) -> Self:
        if self.execution == "unknown" and self.guards:
            raise ValueError("unknown import context cannot assert guards")
        if len(set(self.guards)) != len(self.guards):
            raise ValueError("import guards must be unique")
        return self


class _LocatedImport(_ArchitectureEvidence):
    context: ImportContext = ImportContext()


class ImportEdge(_LocatedImport):
    state: Literal["internal"] = "internal"
    importer: _Text
    imported: _Text
    path: ProjectPath
    span: SourceSpan


class UnresolvedImport(_LocatedImport):
    state: Literal["unresolved"] = "unresolved"
    importer: _Text
    path: ProjectPath
    span: SourceSpan
    expression: _Text
    reason: Literal[
        "dynamic-import",
        "missing-internal-module",
        "ambiguous-module",
        "relative-import-outside-package",
        "star-import",
        "unresolved-package-member",
    ]


class ExternalImport(_LocatedImport):
    state: Literal["external"] = "external"
    importer: _Text
    imported: _Text
    path: ProjectPath
    span: SourceSpan


ImportObservation = Annotated[
    ImportEdge | UnresolvedImport | ExternalImport, Field(discriminator="state")
]


class AnalyzedArchitectureFile(_ArchitectureEvidence):
    state: Literal["analyzed"] = "analyzed"
    path: ProjectPath
    module: _Text
    source_sha256: _Hash
    imports: tuple[ImportObservation, ...] = ()


class UnresolvedArchitectureFile(_ArchitectureEvidence):
    state: Literal["unresolved"] = "unresolved"
    path: ProjectPath
    source_sha256: _Hash
    reason: Literal["outside-source-roots", "ambiguous-module", "invalid-module-path"]


class FailedArchitectureFile(_ArchitectureEvidence):
    state: Literal["failed"] = "failed"
    path: ProjectPath
    diagnostic: Diagnostic


ArchitectureFile = Annotated[
    AnalyzedArchitectureFile | UnresolvedArchitectureFile | FailedArchitectureFile,
    Field(discriminator="state"),
]


class ArchitectureViolation(_ArchitectureEvidence):
    edge: ImportEdge
    rule: ForbiddenDependency


def _legacy_context(value: object) -> object:
    """Old projections omitted context; hydrate only that absent field as unknown."""
    if isinstance(value, list):
        return [_legacy_context(item) for item in value]
    if isinstance(value, Mapping):
        fields = {key: _legacy_context(item) for key, item in value.items()}
        if "importer" in fields and "span" in fields and "context" not in fields:
            fields["context"] = ImportContext().model_dump(mode="json")
        return fields
    return value


def _within(module: str, boundary: str) -> bool:
    return module == boundary or module.startswith(boundary + ".")


def _finish_order(graph: dict[str, set[str]]) -> list[str]:
    seen: set[str] = set()
    order: list[str] = []
    for start in sorted(graph):
        stack = [(start, False)]
        while stack:
            node, finished = stack.pop()
            if finished:
                order.append(node)
            elif node not in seen:
                seen.add(node)
                stack.append((node, True))
                stack.extend((target, False) for target in sorted(graph[node], reverse=True))
    return order


def _components(graph: dict[str, set[str]]) -> tuple[tuple[str, ...], ...]:
    """Find strongly connected components without a recursion-depth limit."""
    reverse: dict[str, set[str]] = {node: set() for node in graph}
    for node, targets in graph.items():
        for target in targets:
            reverse[target].add(node)
    seen: set[str] = set()
    components = []
    for start in reversed(_finish_order(graph)):
        if start in seen:
            continue
        component: set[str] = set()
        pending = [start]
        while pending:
            node = pending.pop()
            if node not in seen:
                seen.add(node)
                component.add(node)
                pending.extend(reverse[node] - seen)
        if len(component) > 1 or start in graph[start]:
            components.append(tuple(sorted(component)))
    return tuple(sorted(components))


class ArchitectureReport(_ArchitectureEvidence):
    schema_version: Literal["1"] = "1"
    experiment: Literal["python-direct-imports-1"] = "python-direct-imports-1"
    tool_version: _Text
    source: SourceIdentity
    config: AnalysisConfig
    policy: ArchitecturePolicy
    files: tuple[ArchitectureFile, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    inventory_coverage: tuple[Coverage, ...] = ()
    excluded_directories: tuple[ExcludedDirectory, ...] = ()
    interpretation: tuple[str, ...] = (
        "Unscored direct static Python imports within selected source roots. "
        "Target code is never executed.",
        "Forbidden rules include descendants and apply to direct edges only. "
        "Cycles are strongly connected components.",
        "External imports are not resolved. Dynamic imports, ambiguous modules and "
        "missing internal targets remain unresolved.",
        "Conditional imports are included as source relationships, not proof of runtime execution. "
        "No findings does not prove architectural conformance.",
        "Import context separates eager or deferred syntax from conditional and type-checking "
        "guards. All edges still contribute to source cycles and declared-rule checks. "
        "Old reports without context remain unknown.",
    )

    @model_validator(mode="wrap")
    @classmethod
    def validate_projections(cls, value: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        if not isinstance(value, Mapping):
            return handler(value)
        fields = dict(value)
        supplied = {name: fields.pop(name) for name in cls.model_computed_fields if name in fields}
        result = handler(fields)
        expected = result.model_dump(mode="json")
        if any(
            _legacy_context(projection) != expected[name] for name, projection in supplied.items()
        ):
            raise ValueError("architecture projections must match source evidence")
        return result

    @computed_field
    @property
    def edges(self) -> tuple[ImportEdge, ...]:
        return tuple(
            item
            for file in self.files
            if isinstance(file, AnalyzedArchitectureFile)
            for item in file.imports
            if isinstance(item, ImportEdge)
        )

    @computed_field
    @property
    def unresolved(self) -> tuple[UnresolvedImport | UnresolvedArchitectureFile, ...]:
        return tuple(
            file for file in self.files if isinstance(file, UnresolvedArchitectureFile)
        ) + tuple(
            item
            for file in self.files
            if isinstance(file, AnalyzedArchitectureFile)
            for item in file.imports
            if isinstance(item, UnresolvedImport)
        )

    @computed_field
    @property
    def violations(self) -> tuple[ArchitectureViolation, ...]:
        return tuple(
            ArchitectureViolation(edge=edge, rule=rule)
            for edge in self.edges
            for rule in self.policy.forbidden
            if _within(edge.importer, rule.source) and _within(edge.imported, rule.target)
        )

    def _graph(self) -> dict[str, set[str]]:
        graph: dict[str, set[str]] = {
            file.module: set() for file in self.files if isinstance(file, AnalyzedArchitectureFile)
        }
        for edge in self.edges:
            graph.setdefault(edge.importer, set()).add(edge.imported)
            graph.setdefault(edge.imported, set())
        return graph

    @computed_field
    @property
    def fan_out(self) -> dict[str, int]:
        return {module: len(targets) for module, targets in sorted(self._graph().items())}

    @computed_field
    @property
    def cycles(self) -> tuple[tuple[str, ...], ...]:
        return _components(self._graph())
