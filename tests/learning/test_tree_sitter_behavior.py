"""Observed behavior of py-tree-sitter with the Python grammar.

These learning tests document dependency behavior on which clone extraction may
later rely. They intentionally exercise the third-party parser without importing
project production code.
"""

from collections.abc import Iterator

import tree_sitter_python
from tree_sitter import Language, Node, Parser, Tree

PYTHON_LANGUAGE = Language(tree_sitter_python.language())


def parse(source: bytes) -> Tree:
    """Parse one immutable byte buffer with the configured Python grammar."""
    return Parser(PYTHON_LANGUAGE).parse(source)


def walk(node: Node) -> Iterator[Node]:
    """Yield nodes in source order for focused observations."""
    yield node
    for child in node.children:
        yield from walk(child)


def node_text(node: Node, source: bytes) -> bytes:
    """Read a node through its half-open byte span."""
    return source[node.start_byte : node.end_byte]


def test_comments_are_named_nodes_but_whitespace_is_not_a_node() -> None:
    """Comments need explicit removal; ordinary spacing does not."""
    source = b"left = 1  # trailing\n# standalone\nright = 2\n"

    nodes = tuple(walk(parse(source).root_node))
    comments = tuple(node for node in nodes if node.type == "comment")

    # The Python grammar exposes comments as named syntax nodes, including a
    # trailing comment. A clone normalizer must therefore discard them itself.
    assert [node_text(node, source) for node in comments] == [
        b"# trailing",
        b"# standalone",
    ]
    assert all(node.is_named for node in comments)

    # Spaces and newlines only separate node spans. They do not appear as
    # explicit nodes that need a second trivia filter.
    assert not {"whitespace", "newline"}.intersection(node.type for node in nodes)


def test_docstrings_have_the_same_syntax_shape_as_other_bare_strings() -> None:
    """Docstring removal requires source context, not a docstring node kind."""
    source = b'''"""module docs"""

def example():
    """function docs"""
    value = 1
    """a later bare string"""
'''

    nodes = tuple(walk(parse(source).root_node))
    string_statements = tuple(
        node
        for node in nodes
        if node.type == "expression_statement"
        and len(node.named_children) == 1
        and node.named_children[0].type == "string"
    )

    # Tree-sitter describes syntax, so both real docstrings and a later bare
    # string are expression_statement(string). The adapter must use placement
    # in a module, class, or function body to identify actual docstrings.
    assert [node_text(node, source) for node in string_statements] == [
        b'"""module docs"""',
        b'"""function docs"""',
        b'"""a later bare string"""',
    ]
    assert not any(node.type == "docstring" for node in nodes)


def test_identifiers_and_literals_have_stable_kinds_and_distinct_text() -> None:
    """The grammar exposes token categories needed for explicit normalization."""
    first = b'result = transform(source, "red", 7)\n'
    second = b'output = transform(payload, "blue", 42)\n'

    first_leaves = tuple(
        node for node in walk(parse(first).root_node) if node.is_named and not node.named_children
    )
    second_leaves = tuple(
        node for node in walk(parse(second).root_node) if node.is_named and not node.named_children
    )

    # Renaming identifiers and replacing literals preserves the named leaf
    # kinds. Their byte text still differs, so exact and normalized matching
    # can be separate, versioned policies.
    assert [node.type for node in first_leaves] == [node.type for node in second_leaves]
    assert [node_text(node, first) for node in first_leaves] != [
        node_text(node, second) for node in second_leaves
    ]
    assert {"identifier", "string_content", "integer"}.issubset(node.type for node in first_leaves)


def test_formatting_is_absent_from_the_tree_but_comments_remain() -> None:
    """Formatting normalization is structural; comment removal is explicit."""
    compact = b"total=price+1\n"
    formatted = b"total = price + 1  # explanation\n"

    compact_nodes = tuple(walk(parse(compact).root_node))
    formatted_nodes = tuple(walk(parse(formatted).root_node))

    compact_shape = [node.type for node in compact_nodes]
    formatted_shape_without_comments = [
        node.type for node in formatted_nodes if node.type != "comment"
    ]

    assert compact_shape == formatted_shape_without_comments
    assert any(node.type == "comment" for node in formatted_nodes)


def test_invalid_source_returns_recovery_nodes_instead_of_raising() -> None:
    """Parse failure is reported in the tree and can be diagnosed per file."""
    source = b"value = )\nafter = 2\n"

    tree = parse(source)
    recovery_nodes = tuple(
        node for node in walk(tree.root_node) if node.is_error or node.is_missing
    )

    # Parser.parse returns a Tree even for malformed input. The adapter must
    # inspect has_error and recovery nodes rather than expect an exception.
    assert tree.root_node.has_error
    assert recovery_nodes
    assert any(node.is_error for node in recovery_nodes)
    assert all(0 <= node.start_byte <= node.end_byte <= len(source) for node in recovery_nodes)


def test_byte_spans_and_point_columns_count_utf8_bytes() -> None:
    """Node spans are half-open byte coordinates, including point columns."""
    source = "é = '✓'\nanswer = é\n".encode()

    identifiers = tuple(
        node
        for node in walk(parse(source).root_node)
        if node.type == "identifier" and node_text(node, source) == "é".encode()
    )
    first, second = identifiers

    assert (first.start_byte, first.end_byte) == (0, len("é".encode()))
    assert (first.start_point.row, first.start_point.column) == (0, 0)
    assert (first.end_point.row, first.end_point.column) == (0, len("é".encode()))

    expected_second_start = len("é = '✓'\nanswer = ".encode())
    assert (second.start_byte, second.end_byte) == (
        expected_second_start,
        expected_second_start + len("é".encode()),
    )
    assert (second.start_point.row, second.start_point.column) == (
        1,
        len(b"answer = "),
    )
    assert (second.end_point.row, second.end_point.column) == (
        1,
        len("answer = é".encode()),
    )

    # Slicing [start_byte:end_byte] recovers the exact token, confirming that
    # end_byte is exclusive and spans must be applied to bytes, not text indices.
    assert node_text(first, source).decode() == "é"
    assert node_text(second, source).decode() == "é"
