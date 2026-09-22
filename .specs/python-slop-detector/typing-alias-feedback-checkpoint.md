# Typing assignment-alias feedback

The external v0.7.0 evaluation reproduced an overconfident import-context label:

```python
import typing as t
other = t
other.TYPE_CHECKING = True
if t.TYPE_CHECKING:
    import sample.storage
```

The released tool labels the storage import `eager` / `type-checking`. The fixed
tool labels it `eager` / `conditional`. Both retain its edge, declared-rule
violation, and source cycle. This corrects an interpretation bug, not a policy
bypass or an established application defect.

The fix invalidates trust when an imported typing module is stored or passed as
a value, or exposed through special attributes such as its mutable namespace.
It applies across imported module aliases. Direct flag imports and ordinary
attribute reads remain supported. This deliberately does not trace arbitrary
aliases: even an escape without a visible mutation can become conditional.

## Validation

- An independent test author established 23 behavioral failures and seven
  preservation controls before implementation. All 30 tests now pass.
- All 82 focused architecture and import-context tests pass. They cover chained,
  annotated and container assignments, calls, namespace escape, API/CLI agreement,
  retained edges/violations/cycles, and nonexecution of target source.
- The complete suite passes 2,099 tests with 93.84% package coverage. Four
  distribution-install tests are skipped in that development run.
- Ruff check/format, Pyright, and all five import contracts pass.
- Complete score JSON on the same source exactly matches the released v0.7.0
  executable. No metric, threshold, calibration, or source-selection rule changed.
- On the synthetic reproduction, old/new architecture reports are identical
  after removing only import context metadata. The label change is the intended
  difference; the edge is never removed.

The broader private corpus was not rerun locally. Its reported 1,707/1,708 result
remains the external assessment, not a result retroactively changed by this fix.
Local evidence is retained under `.tmp/typing-escape-*`; no private corpus files
or review artifacts are committed. The published v0.7.0 artifacts remain unchanged.
