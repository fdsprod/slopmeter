# Experimental coupled-state review

> Release status: the implemented features described here shipped in [v0.4.0](https://github.com/fdsprod/slopmeter/releases/tag/v0.4.0). Hosted CI passed. Validation counts and pre-release status statements below describe the original checkpoint.

## TB-1: Repeated cross-field rejection guards

Question: can one read-only command connect a model invariant to repeated consumer
checks while keeping calibrated measurements unchanged?

Layers: CLI -> source inventory -> Python AST detector -> experimental report ->
JSON and terminal evidence. Budget: one detector, same-file dataclasses, directory
scans only. No scoring, mutation testing, source execution, or automatic fixes.

The command is `slop models --root . [--config FILE] [--lang py] [--strict] [--json]`.
It uses normal Git ignores, exclusions, generated markers, and cohort selection.
It does not call the calibrated scan pipeline or add a rule to M2.

Detect a directly imported, top-level `@dataclass` with no inheritance. Supported
fields are directly annotated `bool` or nullable `T | None`. A `__post_init__`
method must reject a predicate involving at least two such fields, including a
boolean and a nullable field. The `if` body must consist of an explicit raise.
At least two distinct top-level functions with a parameter annotated as the local
model must repeat that predicate. Consumer branches need not raise.

Compare supported predicate AST structure after normalizing only receiver names.
Support boolean and/or/not, direct boolean fields, and `is None`/`is not None`
checks on nullable fields. Do not infer logical equivalence, imports, aliases,
inheritance, dynamic attributes, or behavior across calls. Uncertain bindings,
rebound model parameters, nested scopes and shadowed declarations are not evidence.
The experiment must be conservative about field writes before checks. Only the
first statement after a docstring can supply a guard. All directly annotated fields
must use supported boolean/nullable forms. Custom constructors, `init=False`, and
replaced annotated fields or post-init methods are unresolved. Variadic annotations
do not identify model instances.

The first version supports `from dataclasses import dataclass` and its explicit
import alias, with decorator calls such as `@dataclass(frozen=True)`. It supports
bare model parameter annotations and quoted bare names. Pydantic, TypedDict,
inherited/nested models, Optional aliases, and cross-file consumers remain outside
this experiment. Unsupported model classes and ambiguous bindings are reported as
unresolved, not clean. Ordinary classes may be listed as unsupported.

## Data contract

Module `domain.model_review` defines frozen extra-forbid models. Report
`ModelReviewReport` has schema_version="1", experiment="py-coupled-state-1",
tool_version, source (DirectorySourceIdentity), config, files, inventory_coverage,
diagnostics, excluded_directories, and interpretation text explaining limitations.
There is no score or affected-line numerator.

`files` is a tagged union by state. An `analyzed` file has path, cohort,
source_sha256, and models. A `failed` file has path, cohort, optional source_sha256,
and diagnostic. File paths are unique. A model assessment is tagged by state:
`analyzed` has name, span, findings; `unresolved` has name, span, reason. Failed
files cannot have successful findings. Empty analyzed findings mean only that the
narrow experiment found no qualifying repeated guard.

A `CoupledStateFinding` has kind="coupled-state", fields (at least two
`ModelField` records with name, kind="boolean"|"nullable", declaration span),
predicate (normalized receiver name `model`), validator (`GuardLocation` with
symbol and predicate span), and consumers (at least two `GuardLocation` records
with distinct symbols). Locations are in the containing file. Names and fields are
unique. The finding belongs to the enclosing model assessment. Validator must be
inside that model span. All locations are positive ordered source spans.

Related locations and explicit outcomes prevent a failed parse or unresolved model
from looking like a clean result. This evidence is a projection of source, separate
from metric evidence and persisted clone decisions. A repeated guard does not
prove a defect or justify removing boundary validation.

## Validation

Independent tests precede implementation: positive fixtures, independent flags,
model-only validation, one consumer, duplicated guards in one consumer, shadowed
bindings, parameter reassignment, field mutation, inherited/unsupported models,
parse failures, no target execution, Git ignores, external config, and unchanged
ordinary reports. Run on this codebase and retain findings or empty results with
coverage limits. Independent repository holdouts are still needed before scoring.


## Completed validation

- 1,377 deterministic tests passed on Windows Python 3.12. Branch-inclusive
  coverage is 96.39 percent. All four wheel/source installation tests passed.
  An installed-wheel `models` command also found the seeded candidate.
- All 50 new detector/domain/service/CLI cases passed on Python 3.13 and 3.14.
- Ruff, formatting, Pyright, and all five import contracts passed.
- Paired fixtures cover a validator plus two or three consumers, aliases and quoted
  annotations, independent flags, missing/reordered predicates, one consumer,
  duplicate symbols, reassignment, field mutation, nested scopes, shadowed names,
  property replacements, disabled/custom constructors, replaced post-init hooks,
  variadic annotations, and definition-time rebinding through default expressions.
- The positive CLI fixture produced one finding with declaration lines 5/6,
  validator line 8, and consumer lines 12/17. No source was executed.
- The repository scan read 169 selected Python files. One deliberate malformed
  fixture failed parsing. It reported 178 unresolved class declarations, zero
  supported model assessments, and zero candidates. This is a coverage limit,
  not evidence that the models are correct. The repository chiefly uses Pydantic
  models and dataclasses with field forms outside this experiment.
- Official installed v0.3.0 and the updated tool produced exactly equal ordinary
  JSON score reports on this working tree. Both reported production score 2.1 on
  71 production files. No metric, threshold, or calibration resource changed.
- Local proof artifacts are in `.tmp/models-confirmation/`: self and seeded model
  reports, terminal evidence, and both ordinary score reports. No private external
  evaluation source or artifacts were copied.

This experiment does not yet estimate precision, recall, or false-positive burden
on independent repositories. Pydantic/TypedDict resolution and additional guard
positions require their own paired examples before widening this scope. Changes
are committed locally and are not included in the published v0.3.0 release.
