"""Observed Radon 6 behavior that the Python complexity adapter will rely on.

These tests interrogate Radon directly. They are executable research notes, not tests
of slop.measure production code.
"""

from textwrap import dedent

import pytest
from radon.complexity import cc_visit
from radon.raw import analyze
from radon.visitors import Class, Function

CALLABLE_SOURCE = dedent(
    """\
    def outer(flag):
        def middle(value):
            def inner(candidate):
                if candidate:
                    return 1
                return 0

            if value:
                return inner(value)
            return 0

        if flag:
            return middle(flag)
        return 0


    class Handler:
        def first(self, flag):
            if flag:
                return 1
            return 0

        def second(self, values):
            return [value for value in values if value]
    """
)


def test_closures_are_recursive_while_methods_are_also_top_level_results() -> None:
    """Radon nests closures, but returns each method both with its class and globally."""
    blocks = cc_visit(CALLABLE_SOURCE)
    functions = [block for block in blocks if isinstance(block, Function)]
    classes = [block for block in blocks if isinstance(block, Class)]

    assert [function.name for function in functions] == ["outer", "first", "second"]
    assert [class_block.name for class_block in classes] == ["Handler"]

    outer = functions[0]
    middle = outer.closures[0]
    inner = middle.closures[0]
    handler = classes[0]

    # Observation: nested callables are only reachable through recursive `closures`.
    assert [closure.name for closure in outer.closures] == ["middle"]
    assert [closure.name for closure in middle.closures] == ["inner"]
    assert inner.closures == []
    assert inner not in functions

    # Observation: methods occur in both collections, so an adapter must deduplicate them.
    assert handler.methods == functions[1:]
    assert [method.is_method for method in handler.methods] == [True, True]
    assert [method.classname for method in handler.methods] == ["Handler", "Handler"]


def test_complexity_is_per_callable_and_class_records_are_aggregates() -> None:
    """Closure branches do not inflate parents; class aggregates use separate values."""
    blocks = cc_visit(CALLABLE_SOURCE)
    functions = [block for block in blocks if isinstance(block, Function)]
    handler = next(block for block in blocks if isinstance(block, Class))

    outer = functions[0]
    middle = outer.closures[0]
    inner = middle.closures[0]

    # Observation: each callable starts at one and owns only its own decision points.
    assert (outer.complexity, middle.complexity, inner.complexity) == (2, 2, 2)
    assert [method.complexity for method in handler.methods] == [2, 3]

    # Observation: a Class is an aggregate, not another callable. Its public
    # `complexity` and `real_complexity` also differ, so M4 must exclude both.
    assert handler.complexity == 4
    assert handler.real_complexity == 6


def test_callable_spans_start_at_def_and_end_on_the_last_statement() -> None:
    """Radon spans are one-based and inclusive, and they omit decorator lines."""
    source = dedent(
        """\
        @decorator
        def decorated(
            flag,
        ):
            if flag:
                return 1
            return 0


        class Handler:
            @classmethod
            def build(
                cls,
                flag,
            ):
                if flag:
                    return cls()
                return None
        """
    )

    blocks = cc_visit(source)
    decorated = next(
        block for block in blocks if isinstance(block, Function) and block.name == "decorated"
    )
    build = next(block for block in blocks if isinstance(block, Function) and block.name == "build")
    handler = next(block for block in blocks if isinstance(block, Class))

    # Observation: both endpoints are inclusive; decorators are outside callable spans.
    assert (decorated.lineno, decorated.endline) == (2, 7)
    assert (build.lineno, build.endline) == (12, 18)
    assert (handler.lineno, handler.endline) == (10, 18)

    # Observation: complexity records provide no callable SLOC value. The adapter
    # must intersect these spans with the project's shared physical-SLOC line set.
    assert not hasattr(decorated, "sloc")


def test_raw_sloc_excludes_comments_docstrings_and_blank_lines() -> None:
    """Radon's file-level raw SLOC is physical code, not logical statement count."""
    source = dedent(
        '''\
        """Module documentation."""
        # A regular comment.
        def example(flag):
            """Function documentation."""
            if flag:
                return 1

            return 0
        '''
    )

    metrics = analyze(source)

    # Observation: only `def`, `if`, and the two `return` lines count as SLOC.
    assert metrics.loc == 8
    assert metrics.sloc == 4
    assert metrics.lloc == 6
    assert metrics.comments == 1
    assert metrics.blank == 1
    assert metrics.single_comments == 3


def test_syntax_errors_propagate_with_source_location() -> None:
    """Radon raises SyntaxError rather than returning partial complexity results."""
    with pytest.raises(SyntaxError) as caught:
        cc_visit("def broken(:\n    pass\n")

    assert caught.value.lineno == 1
