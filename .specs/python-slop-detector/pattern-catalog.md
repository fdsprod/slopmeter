# Python pattern catalog

TB-3 defines these twenty rules. Each rule has a stable `py.` identifier, one
category, and positive and negative fixtures. The first catalog uses Python AST
nodes and local scope facts. It does not require a project reference index.

Findings identify code for review. They do not authorize an automatic rewrite.
M2 counts the union of finding spans intersected with the file's exact SLOC set.
Overlapping findings count each physical source line once.

## Shared detection limits

- Resolve builtin names conservatively. Skip a builtin-dependent rule when a
  parameter, type parameter, assignment, import, definition, enclosing binding, or class binding
  can shadow that name. Import-star and dynamic `exec` make this proof unavailable.
- A stable local name is a function parameter or ordinary local binding. It is
  not a global, nonlocal, attribute, subscript, or captured name. Skip name-based
  simplifications when `exec`, `eval`, `locals`, or `globals` makes local use unclear.
- Match real constants by type. `True` and `False` are boolean constants, not
  integer literals that happen to compare equal to them.
- Count loads and stores in the owning lexical scope. A nested scope that refers
  to the candidate name prevents a single-use proof. Public naming alone never
  proves that a callable is unused.
- Use source tokens to locate `else`, `except`, and `finally` headers. Comments,
  blank lines, and multiline expressions make a guessed preceding line unreliable.
- Header spans run from the keyword through its suite colon. They include all
  physical header lines when the header spans several lines. Expression spans use
  the full AST node. All spans are one-based and inclusive.
- Preserve explicit type boundaries, including PEP 484 type comments on helper
  definitions and return-value bindings. The default AST does not retain these
  comments, so the rules also inspect source tokens.
- A literal f-string has no interpolation. A format specification inside an
  interpolated f-string is not a separate string to simplify. Suggested conversions
  must preserve the decoded value, including escaped braces.

## Redundancy

| Rule ID | Trigger and positive example | Keep cases | Finding span |
|---|---|---|---|
| `py.boolean-conditional` | `True if condition else False`. Both arms are exact boolean constants. | `1 if condition else 0`, nonconstant arms, or an arm with effects. | Full conditional expression. |
| `py.negated-boolean-conditional` | `False if condition else True`. Both arms are exact boolean constants. | Nonboolean or nonconstant arms. | Full conditional expression. |
| `py.literal-fstring` | A `JoinedStr` with no `FormattedValue`, such as `f"hello"`. | Any interpolation, conversion, or format expression. | Full string expression. |
| `py.literal-identity-comprehension` | `[item for item in (1, 2)]`: one synchronous generator, a simple name target, and the same name as the element. The iterable is a list or tuple literal. | Filters, multiple generators, async iteration, unpacking targets, transformed elements, variable iterables, or starred elements in the iterable. | Full comprehension. |
| `py.redundant-literal-container` | One unshadowed builtin constructor around its matching literal: `list([1, 2])`, `tuple((1, 2))`, `set({1, 2})`, or `dict({"a": 1})`. | Shadowed constructors, different literal kinds, variable arguments, keywords, or argument unpacking. | Full constructor call. |

## Control flow

The four `else` rules require an `if` body whose final direct statement has the
specified terminating kind. The body must have a real `else` suite. An `elif`
chain is outside these rules. A terminating statement nested inside a `try`,
`with`, loop, or another conditional does not establish the required direct exit.

| Rule ID | Trigger and positive example | Keep cases | Finding span |
|---|---|---|---|
| `py.redundant-else-after-return` | `if condition: return value` followed by `else: work()`. | The branch only conditionally returns, or has a later direct statement. | `else` header only. |
| `py.redundant-else-after-raise` | `if condition: raise Error` followed by `else: work()`. | A nested or conditional raise, or a later direct statement. | `else` header only. |
| `py.redundant-else-after-break` | Inside a loop, `if condition: break` followed by `else: work()`. | A break inside another loop or a nested conditional. | `else` header only. |
| `py.redundant-else-after-continue` | Inside a loop, `if condition: continue` followed by `else: work()`. | A continue inside another loop or a nested conditional. | `else` header only. |
| `py.merge-nested-if` | `if first:` contains only `if second: work()`. Neither conditional has an else suite. | Sibling statements, an else on either conditional, or an `elif` chain. | Inner `if` header only. |

## Defensive code

| Rule ID | Trigger and positive example | Keep cases | Finding span |
|---|---|---|---|
| `py.redundant-except-reraise` | A `try` has one bare `except:` whose only statement is bare `raise`. There is no `else` or `finally`. | Typed handlers, bound exception names, multiple handlers, logging, cleanup, new exceptions, or explicit causes. | Handler header through the bare raise. |
| `py.empty-finally` | A `finally:` suite contains exactly `pass`. | Any other cleanup statement, including an expression, or multiple statements. Other handlers on the owning try do not prevent this finding. | Finally header through the pass. |
| `py.redundant-none-fallback` | `value if value is not None else None`, using the same stable local name in the test and true arm. | Calls, attributes, subscripts, globals, nonlocals, captured names, equality tests, or another fallback. | Full conditional expression. |
| `py.redundant-dict-get-default` | A dictionary literal calls `.get(key, None)` with exactly two positional arguments, such as `{"a": 1}.get("a", None)`. | A variable or custom receiver, a different method, a non-None default, keywords, or argument unpacking. | Full method call. |
| `py.redundant-literal-none-guard` | In a function, an ordinary local assignment of a non-None literal is immediately followed in the same suite by `if value is None:`. Example: `value = 1` then `if value is None: raise Error`. | Unknown values, None assignment, multiple targets, annotated assignments, intervening statements, globals, nonlocals, or dynamic local access. | Guard `if` header only. |

## Abstraction

| Rule ID | Trigger and positive example | Keep cases | Finding span |
|---|---|---|---|
| `py.redundant-pass` | A direct `pass` in a class or function body that also contains a real statement, such as `class C: pass; value = 1`. | A pass-only body, a docstring plus pass, an ellipsis stub plus pass, or a pass in a required otherwise-empty control-flow suite. | Exact pass statement. |
| `py.explicit-object-base` | `class C(object): ...`, with exactly one base, an unshadowed `object`, no class keywords, and no decorators. | Additional bases, metaclass keywords, decorators, or shadowed `object`. | Base name `object`. |
| `py.explicit-default-metaclass` | `class C(metaclass=type): ...`, with no bases, no other keywords, no decorators, and unshadowed `type`. | Bases, other class keywords, decorators, or a custom or shadowed metaclass. | The `metaclass=type` keyword argument. |
| `py.trivial-wrapper` | A private nested synchronous helper has one statement: `return target(parameter, ...)`. It forwards every ordinary parameter unchanged, in order, to a bare target name. Its only use is a direct call in the immediately following statement of the enclosing function. | Module functions, methods, public names, decorators, docstrings, annotations, type parameters, defaults, positional-only or keyword-only parameters, variadic parameters, keyword forwarding, async, yield, await, recursive calls, rebinding, callbacks, additional uses, or dynamic local access. | Full helper definition. |
| `py.single-use-return-binding` | An ordinary assignment `temporary = expression` is immediately followed by `return temporary` in the same function suite. The name has exactly one store and one load in that scope. | Annotated or multiple-target assignments, other uses or stores, nested captures, intervening statements, globals, nonlocals, dynamic local access, or yield/await in the expression. | Assignment statement only. |

## False-positive limits

These rules report syntax, not functional correctness. A local helper can still
express a useful concept. A named return value can still improve explanation.
Keep these cases reviewable through rule IDs and finding locations; never present
them as proven bugs.

Python reflection and runtime mutation can observe differences that static scope
analysis cannot prove away. The guards above reject visible uncertainty. The
catalog does not claim whole-program equivalence or infer public API usage.

A wrapper's immediate use must be the direct value of an expression, return, or
assignment statement. A call inside a loop, conditional, or larger expression does
not establish this guard.

Every rule needs a positive fixture and fixtures for its listed keep cases.
Builtin-dependent rules need explicit shadowing fixtures. Local-use rules need
closures and rebinding fixtures. Keyword spans need comment and multiline fixtures.
Catalog registration rejects duplicate IDs and preserves a stable rule order and
catalog version.
