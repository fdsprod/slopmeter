"""One immutable parsed source needs one tokenization per pattern scan."""

import ast
import tokenize
from collections.abc import Callable, Iterator

import pytest

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import AnalyzedPatterns, FileEvidence
from slop_measure.domain.source import ProjectPath
from slop_measure.languages.python.patterns import (
    PythonParsedUnit,
    PythonProjectContext,
    run_patterns,
)


@pytest.mark.parametrize("type_comment", [False, True])
def test_pattern_scan_tokenizes_source_once_across_multiple_return_candidates(
    monkeypatch: pytest.MonkeyPatch, type_comment: bool
) -> None:
    assignments = "".join(f"    value_{index} = work({index})\n" for index in range(7))
    typed = "  # type: int" if type_comment else ""
    source = "".join(
        f"def example_{index}():\n{assignments}    result = work(7){typed}\n    return result\n"
        for index in range(2)
    )
    tree = ast.parse(source)
    file = FileEvidence.model_validate(
        {
            "path": "app.py",
            "language": "python",
            "cohort": "production",
            "parse_state": "parsed",
            "sloc": 20,
            "sloc_lines": list(range(1, 21)),
        }
    )
    unit = PythonParsedUnit(tree=tree, file=file, source=source)
    context = PythonProjectContext(paths=(ProjectPath("app.py"),))
    config = AnalysisConfig(enabled_rules=frozenset({"py.single-use-return-binding"}))
    original = tokenize.generate_tokens
    calls = 0

    def counted(readline: Callable[[], str]) -> Iterator[tokenize.TokenInfo]:
        nonlocal calls
        calls += 1
        return original(readline)

    monkeypatch.setattr(tokenize, "generate_tokens", counted)
    result = run_patterns(unit, context, config)
    assert isinstance(result, AnalyzedPatterns)
    if type_comment:
        assert result.findings == ()
    else:
        assert len(result.findings) == 2
        assert {finding.rule_id for finding in result.findings} == {"py.single-use-return-binding"}
        assert [
            (finding.span.start_line, finding.span.end_line) for finding in result.findings
        ] == [(9, 9), (19, 19)]
    # Both candidates inspect the same immutable source. The tokenization hook
    # must run, but repeating that full-source work cannot add information.
    assert calls == 1
