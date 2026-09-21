# Candidate detection methods

Research date: 2026-09-18. This is an exploration backlog, not an implementation
specification. The detection proposals below are our inferences from the cited
methods and the data-structure-design skill. The sources do not validate a
general-purpose slop score.

The most useful next direction is to inspect relationships between data and
behavior. The current catalog has twenty local Python syntax rules. It also
measures clones and complexity. These can identify redundant code, but they do
not establish whether a model permits contradictory states or needs several
writers to keep it consistent.

Keep code quality separate from authorship. An empirical study found that
existing AI-code detectors lacked sufficient generalizability. An authorship
classifier would also answer a different question from whether code needs repair.
See the [research paper](https://arxiv.org/abs/2411.04299).

## Ideas from data-structure-design

| Candidate | Proposed detection | Evidence to show | Limits and keep cases |
|---|---|---|---|
| Coupled flags and nullable fields | Inspect dataclasses, TypedDicts, and Pydantic models. Find guards that reject combinations of fields or require a payload for a particular status. | Model fields, enforcing predicate, and consumers that repeat the same guard. | Several booleans are not inherently wrong. Independent preferences are valid. Runtime validation can correctly enforce constraints that types cannot express. |
| Duplicated derived state | Find stored assignments such as `self.count = len(self.items)`. Trace subsequent writes to the dependency and reads of the stored value. | Derivation, mutation, and later read on a path without recomputation. | Frozen snapshots, projections, caches, descriptors, and aliases need special handling. A derived assignment alone is only a candidate. |
| Missing variant handling | Resolve a local Enum or Literal union, then compare its known cases with `match` or `if` branches. | Declared cases, handled cases, and the omitted case or silent fallback. | Intentional partial handlers and open protocol values need different treatment. A catch-all can be required at a compatibility boundary. |
| Unrelated field groups | Build a graph connecting methods to fields they read and write. Find groups with few shared lifecycle operations. | Field groups and the methods that use each group. | Serialization methods connect every field. DTOs and small cohesive records should not be split merely to improve a metric. |
| Repeated repair of a weak model | Find equivalent cross-field guards or conversion tables repeated across consumers. | The original shape and several repeated repairs. | Revalidation at separate trust boundaries is often required. Repeated checks do not by themselves prove poor design. |

Tagged unions and exhaustive handling have direct support in Python type-checking
tools. [Mypy's documentation](https://mypy.readthedocs.io/en/stable/literal_types.html)
describes tagged unions, `assert_never`, and exhaustive match checking. Start with
locally resolvable declarations or import existing type-checker diagnostics.
Do not attempt to build a complete type checker inside Slopmeter.

The skill's review categories remain useful: violation, deliberate tradeoff,
acceptable, and future pressure. A detector should propose evidence for review.
It cannot infer the next likely business case from source syntax alone.

## Other directions

| Idea | First experiment | Main limitation | Basis |
|---|---|---|---|
| Errors turned into plausible success | Find broad exception handlers returning empty collections, `None`, or success-shaped defaults. Inspect how callers consume them. | A fallback can be intentional. Catching an exception and returning an explicit failure variant is different. | [Ruff blind-except](https://docs.astral.sh/ruff/rules/blind-except/) provides a baseline check. |
| Data-flow-aware redundancy | Extend a few local rules across intervening statements using assignments, branches, and kills of known facts. | Calls, mutation, reflection, and aliases can invalidate facts. Start within one function. | [CodeQL data flow](https://codeql.github.com/docs/writing-codeql-queries/about-data-flow-analysis/) explains flow graphs and local/global analysis. |
| Architecture violations | Import forbidden-dependency, layer, and independence results into review evidence. | Architecture must be declared. Dependency count alone does not establish a violation. | [Import Linter contracts](https://import-linter.readthedocs.io/en/stable/contract_types/). This repo already uses Import Linter for its own boundaries. |
| Change coupling and maintenance hotspots | Rank existing findings using edit frequency. Find modules that repeatedly change together despite having no obvious static relationship. | Exclude bulk formatting, generated files, and large reorganizations. Co-change is a review signal, not causation. | [CodeScene change coupling](https://codescene.com/blog/change-coupling-visualize-the-cost-of-change). |
| Tests that do not detect broken behavior | Import mutation-test results for changed functions. Show surviving mutations beside relevant code. | Survivors can be equivalent mutations or gaps in the test contract. Target execution is required. | [mutmut](https://github.com/boxed/mutmut) is a Python mutation-testing tool. Check platform support before adopting it. |
| Broken lifecycle invariants | Use a declared state model to generate operation sequences and check invariants after each step. | Domain invariants need to be supplied or reviewed. This is optional dynamic validation. | [Hypothesis stateful testing](https://hypothesis.readthedocs.io/en/latest/stateful.html). |

Mutation testing and stateful testing belong in an explicit optional workflow or
an external-results importer. Normal Slopmeter scans currently promise not to
execute target code. They should retain that behavior.

Semgrep is another way to prototype structural rules before adding native
implementations. Its [rule examples](https://semgrep.dev/docs/writing-rules/rule-ideas)
cover structural matching and data-flow use cases. It is an experiment tool here,
not a proposed mandatory dependency.

## A concrete first example

```python
@dataclass
class Result:
    succeeded: bool
    value: Payload | None
    error: str | None
```

This shape permits success with an error and success without a value. That is a
design concern only if the domain forbids those combinations. Stronger evidence
would be a validator rejecting them and repeated consumers checking them.

A proposed finding should say: "These fields encode mutually exclusive outcomes;
three consumers repeat the same consistency check." It should show those source
locations. It should not say: "Three optional fields prove this code is slop."

A union of `Success(value)` and `Failure(error)` would separate the outcomes and
remove those contradictory typed combinations. Python still needs validation at
untrusted runtime boundaries. A public or persisted shape also needs a migration
decision before any redesign.

## Fit with the current implementation

- `languages/python/patterns.py` provides `PythonPatternRule`, `PythonParsedUnit`,
  and `PythonProjectContext`. The context currently contains paths, not a symbol
  index. Cross-file field and variant resolution needs additional analysis.
- Begin with same-file model declarations and consumers. Keep unresolved symbols
  explicit instead of treating missing information as a clean result.
- `PatternFinding` and its validation currently expect rule-level messages and
  one primary span. Relationship findings need a design for related locations and
  instance-specific evidence before implementation.
- Keep these experiments outside the calibrated score at first. M2 measures
  affected source lines. That denominator does not naturally measure model
  consistency, architecture violations, or test effectiveness.
- Retain the existing distinction between failed analysis and an analyzed file
  with no findings. New capabilities need the same coverage reporting.

## Suggested experiment order

1. Build paired fixtures for coupled state fields, stale derived state, and
   missing variant handling. Include independent flags, immutable snapshots,
   valid caches, boundary validation, and intentional partial handlers.
2. Prototype coupled-field detection from explicit cross-field guards. This is
   the closest match to the skill and can produce useful source evidence without
   pretending to know the business rules.
3. Add locally resolved Enum/Literal coverage checks. Distinguish missing known
   cases from future-extension concerns.
4. Prototype derived-state tracing within one class and one function at a time.
   Only claim a stale read when the relevant path and mutation are established.
5. Evaluate on the existing calibration corpus plus manually reviewed examples.
   Label findings independently of authorship. Report precision, missed seeded
   defects, unresolved-analysis rate, and runtime by rule. Include reviewed clean
   examples so low finding counts do not masquerade as accuracy.
6. Use held-out repositories before setting thresholds or score weights. Keep
   multiple findings about the same design issue grouped for review.

The first decision is which evidence we want to establish, not which aggregate
score to add. Coupled-state review offers the most direct skill-to-detector
experiment. Missing variant checks offer a more mechanical starting point.
