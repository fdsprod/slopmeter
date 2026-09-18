"""Retained Radon AST observations for callable extraction without reparsing."""

import ast

import pytest
from radon.complexity import add_inner_blocks, cc_visit_ast
from radon.visitors import Class, Function


def test_cc_visit_ast_accepts_the_existing_tree_without_parsing_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree = ast.parse("def example(flag):\n    if flag: return 1\n    return 0\n")

    def reject_parse(*args: object, **kwargs: object) -> ast.Module:
        raise AssertionError("Radon must reuse the existing AST")

    monkeypatch.setattr(ast, "parse", reject_parse)
    blocks = cc_visit_ast(tree)
    # AST entrypoint traverses directly; it does not pass through code2ast.
    assert len(blocks) == 1
    assert isinstance(blocks[0], Function)
    assert (blocks[0].name, blocks[0].complexity) == ("example", 2)


def test_local_class_methods_are_missing_from_whole_module_results() -> None:
    tree = ast.parse(
        "def outer():\n"
        "    class Local:\n"
        "        def method(self, flag):\n"
        "            if flag: return 1\n"
        "            return 0\n"
        "    return Local\n"
    )
    flattened = add_inner_blocks(cc_visit_ast(tree))
    # Function traversal retains child functions but drops child classes.
    # Radon's flattening helper cannot recover facts absent from its input.
    assert [block.fullname for block in flattened] == ["outer"]
    method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "method"
    )
    direct = cc_visit_ast(method)
    assert len(direct) == 1
    assert (direct[0].name, direct[0].complexity) == ("method", 2)
    # Visiting a callable alone loses method ownership, so AST owns qualification.
    assert direct[0].is_method is False
    assert direct[0].classname is None


def test_nested_classes_and_async_methods_need_ast_qualified_identities() -> None:
    tree = ast.parse(
        "class Outer:\n"
        "    class Inner:\n"
        "        async def method(self, flag):\n"
        "            def nested(): return 0\n"
        "            if flag: return nested()\n"
        "            return 0\n"
    )
    blocks = cc_visit_ast(tree)
    assert len(blocks) == 1
    assert isinstance(blocks[0], Class)
    inner = blocks[0].inner_classes[0]
    method = inner.methods[0]
    # Async functions receive ordinary Function records. Direct records only
    # know the immediate class; flattened closure names lose the class prefix.
    assert (method.fullname, method.complexity) == ("Inner.method", 2)
    functions = [block for block in add_inner_blocks(blocks) if isinstance(block, Function)]
    assert {(block.fullname, block.complexity) for block in functions} == {
        ("Outer.Inner.method", 2),
        ("method.nested", 1),
    }
    async_node = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef))
    assert cc_visit_ast(async_node)[0].complexity == 2


def test_duplicate_callable_names_remain_distinct_by_source_position() -> None:
    tree = ast.parse("def repeated(): return 1\ndef repeated(): return 2\n")
    blocks = cc_visit_ast(tree)
    # Runtime rebinding does not remove earlier source declarations.
    assert [block.fullname for block in blocks] == ["repeated", "repeated"]
    assert [(block.lineno, block.col_offset) for block in blocks] == [(1, 0), (2, 0)]


def test_radon_endline_can_omit_closing_lines_of_multiline_statements() -> None:
    tree = ast.parse("def example():\n    return (\n        1\n    )\n")
    function = tree.body[0]
    record = cc_visit_ast(function)[0]
    # Radon tracks visited node start lines. The AST end position includes the
    # final closing delimiter, which the shared SLOC definition counts.
    assert record.endline == 3
    assert function.end_lineno == 4


def test_invalid_ast_missing_required_location_raises_attribute_error() -> None:
    tree = ast.parse("def example():\n    pass\n")
    del tree.body[0].lineno
    # The AST entrypoint trusts parser invariants and has no domain-specific
    # failure result. The adapter must convert analyzer exceptions itself.
    with pytest.raises(AttributeError, match="lineno"):
        cc_visit_ast(tree)
