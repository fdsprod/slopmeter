"""Tree-sitter parsing for versioned Python clone normalization."""

from collections.abc import Iterator

import tree_sitter_python
from tree_sitter import Language, Node, Parser, Tree

NORMALIZATION_VERSION = "py-clones-1"
_LANGUAGE = Language(tree_sitter_python.language())


def walk_nodes(node: Node) -> Iterator[Node]:
    """Visit syntax nodes in source order, including punctuation."""
    yield node
    for child in node.children:
        yield from walk_nodes(child)


def validate_tree(tree: Tree) -> None:
    """Reject recovered or incomplete syntax rather than report partial clones."""
    if tree.root_node.has_error or any(node.is_missing for node in walk_nodes(tree.root_node)):
        raise ValueError("Python clone parser could not parse the complete source.")


def parse_python(source: str) -> Tree:
    """Parse source without executing it or consulting the filesystem."""
    tree = Parser(_LANGUAGE).parse(source.encode("utf-8"))
    validate_tree(tree)
    return tree
