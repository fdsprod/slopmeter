"""Retained Tree-sitter role and suite observations for renamed clone candidates.

These tests query the dependency only. They contain no slop.measure imports or
normalization implementation.
"""

from collections.abc import Iterator

import tree_sitter_python
from tree_sitter import Language, Node, Parser


def parse(source: bytes) -> Node:
    return Parser(Language(tree_sitter_python.language())).parse(source).root_node


def walk(node: Node) -> Iterator[Node]:
    yield node
    for child in node.children:
        yield from walk(child)


def field(node: Node, name: str) -> Node:
    result = node.child_by_field_name(name)
    assert result is not None
    return result


def text(node: Node, source: bytes) -> bytes:
    return source[node.start_byte : node.end_byte]


def test_assignment_call_attribute_and_keyword_roles_are_explicit() -> None:
    source = (
        b'local = source\nlocal = transform(local, mode="fixed")\n'
        b"obj.field = local\nobj.method(local, option=local)\n"
    )
    nodes = tuple(walk(parse(source)))
    assignments = [node for node in nodes if node.type == "assignment"]
    assert field(assignments[0], "left").type == "identifier"
    assert text(field(assignments[0], "left"), source) == b"local"
    assert text(field(assignments[0], "right"), source) == b"source"
    call = field(assignments[1], "right")
    assert text(field(call, "function"), source) == b"transform"
    attribute = field(assignments[2], "left")
    assert attribute.type == "attribute"
    assert text(field(attribute, "object"), source) == b"obj"
    assert text(field(attribute, "attribute"), source) == b"field"
    keywords = [node for node in nodes if node.type == "keyword_argument"]
    assert [text(field(node, "name"), source) for node in keywords] == [b"mode", b"option"]
    # All names are identifier nodes. Their parent fields, not their leaf kind,
    # distinguish renameable storage from external callees and API labels.
    assert all(field(node, "name").type == "identifier" for node in keywords)


def test_module_function_and_nested_suites_have_separate_direct_statement_sequences() -> None:
    source = (
        b'"module docs"\nimport math\ndef f(arg):\n    "docs"\n'
        b"    first = arg\n    if first:\n        nested = first\n"
        b"        consume(nested)\n    consume(first)\n"
    )
    root = parse(source)
    assert [node.type for node in root.named_children] == [
        "expression_statement",
        "import_statement",
        "function_definition",
    ]
    function = root.named_children[2]
    body = field(function, "body")
    assert body.type == "block"
    assert [node.type for node in body.named_children] == [
        "expression_statement",
        "expression_statement",
        "if_statement",
        "expression_statement",
    ]
    nested_body = field(body.named_children[2], "consequence")
    assert nested_body.type == "block"
    assert [text(node, source) for node in nested_body.named_children] == [
        b"nested = first",
        b"consume(nested)",
    ]
    # Descendant statements are not flattened into their parent suite. Direct
    # sibling runs can be extracted without enumerating arbitrary subwindows.
    assert nested_body.parent == body.named_children[2]


def test_definitions_and_decorators_expose_body_boundaries_independently() -> None:
    source = b"@decorate\ndef f(arg):\n    value = arg\n    return value\nclass C:\n    value = 1\n"
    root = parse(source)
    decorated, class_node = root.named_children
    assert decorated.type == "decorated_definition"
    function = field(decorated, "definition")
    assert function.type == "function_definition"
    assert field(function, "parameters").type == "parameters"
    assert [text(node, source) for node in field(function, "body").named_children] == [
        b"value = arg",
        b"return value",
    ]
    assert class_node.type == "class_definition"
    assert [text(node, source) for node in field(class_node, "body").named_children] == [
        b"value = 1"
    ]
    # The decorator wrapper and definition header are distinct from the body.
    # Splitting outer runs at definitions does not lose independently eligible bodies.
    assert field(function, "body").start_point.row == 2


def test_scoping_constructs_are_syntax_nodes_without_resolved_binding_identity() -> None:
    source = (
        b"def f(arg):\n    global cache\n    nonlocal captured\n"
        b"    pair = [item for item in source]\n    callback = lambda arg: arg\n"
        b"    if (value := source):\n        consume(value)\n"
    )
    nodes = tuple(walk(parse(source)))
    assert {"global_statement", "nonlocal_statement", "list_comprehension", "lambda"}.issubset(
        {node.type for node in nodes}
    )
    generator = next(node for node in nodes if node.type == "for_in_clause")
    assert text(field(generator, "left"), source) == b"item"
    assert text(field(generator, "right"), source) == b"source"
    named = next(node for node in nodes if node.type == "named_expression")
    assert text(field(named, "name"), source) == b"value"
    lambda_node = next(node for node in nodes if node.type == "lambda")
    assert text(field(lambda_node, "parameters"), source) == b"arg"
    assert text(field(lambda_node, "body"), source) == b"arg"
    # The outer parameter and both lambda identifiers share the same node kind.
    # The clone policy must supply scope analysis or conservatively keep exact names.
    assert [node.type for node in nodes if text(node, source) == b"arg"] == [
        "identifier",
        "lambda_parameters",
        "identifier",
        "identifier",
    ]


def test_statement_count_and_physical_sloc_are_distinct_for_semicolons() -> None:
    root = parse(b"a = 1; b = 2\n")
    assert len(root.named_children) == 2
    assert [node.type for node in root.named_children] == ["expression_statement"] * 2
    assert {node.start_point.row for node in root.named_children} == {0}
    # Two executable statements occupy one source line. Both configured minima
    # must be checked independently, and line-only self-overlap is not duplication.
    assert root.named_children[0].end_byte < root.named_children[1].start_byte


def test_operators_and_literal_kinds_require_more_than_named_identifier_leaves() -> None:
    source = b'a = 1\nb = 1.0\nc = True\nx = a + b\ny = a - b\ns = "red"\n'
    nodes = tuple(walk(parse(source)))
    assert {"integer", "float", "true", "string"}.issubset({node.type for node in nodes})
    binary = [node for node in nodes if node.type == "binary_operator"]
    assert [text(node, source) for node in binary[0].named_children] == [b"a", b"b"]
    assert [text(node, source) for node in binary[1].named_children] == [b"a", b"b"]
    assert [text(node, source) for node in binary[0].children if not node.is_named] == [b"+"]
    assert [text(node, source) for node in binary[1].children if not node.is_named] == [b"-"]
    # A named-leaf-only encoding would lose the arithmetic operator and merge
    # distinct literal types if it replaced values with one generic placeholder.


def test_fstring_conversion_and_format_specifier_are_explicit_semantic_children() -> None:
    source = b'value = f"{arg!r:03}"\n'
    interpolation = next(node for node in walk(parse(source)) if node.type == "interpolation")
    assert text(field(interpolation, "expression"), source) == b"arg"
    assert text(field(interpolation, "type_conversion"), source) == b"!r"
    assert text(field(interpolation, "format_specifier"), source) == b":03"
    # A string is not automatically trivia: interpolation, conversion, and format
    # semantics must survive normalized clone encoding.
