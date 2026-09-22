# Exception fallback review

Status: implemented and validated in the source checkout after v0.5.0.
This experiment does not change scores, M2,
calibration, or source classification.

## Question

Can a reviewer distinguish an intentional empty fallback from a failed operation
that looks like a successful empty result, using source evidence alone?

`slop errors --root PATH [--config FILE] [--lang py] [--strict] [--json]`
will inspect exception handlers without importing or executing source. It will
show candidates, coverage, unsupported cases, and interpretation on every run.

## Evidence contract

The experiment ID is `py-error-fallback-1`. The report schema is `1`. Its review
family is `error`. All evidence models are frozen and reject unknown fields.

| Model | Fields |
|---|---|
| `ErrorExpression` | `span: SourceSpan`, `expression: nonempty str` |
| `ErrorFallbackFinding` | `kind = "error-as-success"`, `caught: nonempty str`, `protected: SourceSpan`, `operations: tuple[ErrorExpression, ...]`, `fallback: ErrorExpression`, `fallback_kind`, `normal_returns: nonempty tuple[ErrorExpression, ...]` |
| `AnalyzedErrorHandler` | `state = "analyzed"`, `symbol`, `span`, `findings: tuple[ErrorFallbackFinding, ...]` |
| `UnresolvedErrorHandler` | `state = "unresolved"`, `symbol`, `span`, `reason` |
| `AnalyzedErrorFile` | `state = "analyzed"`, `path`, `cohort`, `source_sha256`, `handlers` |
| `FailedErrorFile` | `state = "failed"`, `path`, `cohort`, optional `source_sha256`, error `diagnostic` |
| `ErrorReviewReport` | Existing experimental report envelope, `files`, computed `summary` |

`fallback_kind` is one of `none`, `false`, `zero`, `empty-string`, `empty-bytes`,
`empty-list`, `empty-dict`, or `empty-tuple`. Bare `return` is `none`. Expression
text is normalized with `ast.unparse`; it is evidence, not executable output.
Return evidence spans the return statement, and a bare return has expression
`None`. Handler spans cover the except clause; bare catches use `bare except`.
The protected span covers the try body, including a decorator before the first
definition. Operations include calls in eager definition headers (decorators,
defaults, class bases and keywords). Nested bodies, annotations, lazy type
expressions, and exception handlers are omitted. Operations are possible calls,
not an attribution of which operation raised or an exhaustive exception source.

Each handler gets one outcome. Coverage uses `exception-handlers` as its unit.
An empty file has no handlers; it does not have a successful function assessment.
Failed files keep diagnostics without invented handler counts. Reports accept an
omitted summary and reject a supplied summary that disagrees with their evidence.

## First supported slice

- Inspect synchronous and asynchronous functions, methods, and nested functions.
  Qualified symbols keep lexical function/class names. Do not mix nested scopes.
- Support ordinary `except`, either bare or with a name, attribute, or tuple of
  names/attributes. Preserve the spelling. Do not infer exception inheritance or
  that an identifier resolves to a builtin exception.
- A candidate has a direct final literal/default return in its handler and at
  least one non-default explicit return expression elsewhere in the same function,
  outside exception handlers and nested scopes. This is syntactic corroboration,
  not a proof of reachability, return-type equivalence, or business intent.
- Simple expressions (including logging), assignments, and `pass` before the
  final return are supported. Logging does not prove the result is safe.
- A handler ending in `raise`, or with no return, is assessed with no finding.
  A literal/default return without a corroborating normal return is also assessed
  with no finding. Explicit failure objects and non-default returns are not
  candidates; indirect fallback values (including failure constructor calls)
  remain unresolved. Non-default literals are assessed with no candidate.
- Conditional handler flow, early exits before a final return, `except*`, dynamic
  exception expressions, generators, module/class-level handlers, and handlers
  enclosed by a try/finally remain unresolved with specific reasons. This includes
  an outer finally that can replace the observed return.
- Calls or yields in nested declaration annotations remain unresolved. Local
  annotations and lazy type expressions do not supply eager-operation evidence.
- No exception-return sentinel inference, imported contract resolution, or
  automatic fixes. `None`, `False`, and empty containers can be intentional
  failure/snapshot results. Candidates require a reviewer to inspect the caller
  contract, observability, and whether failure needs a distinct result.

## Validation

Independent test authors cover positive and intentional-fallback controls,
negative reraise/explicit-failure cases, scope isolation, unsupported control
flow, parse failures, source safety, configuration, summaries, and attributed
review lifecycle. Tests precede production code in separate commits.

The final checks include the full suite, static checks, a self-scan and review of
every self-scan candidate, and identical-source score comparison with the prior
checkout. No self-scan outcome can justify project-specific score tuning.
