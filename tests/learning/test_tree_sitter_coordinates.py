"""Retain normal coordinate reads on a multi-function Python syntax tree.

The subprocess contains native parser failures so they cannot stop pytest.
No generated function is imported or executed.
"""

import subprocess
import sys


def test_coordinate_reads_survive_generated_multifunction_source() -> None:
    script = r"""
import os
if os.name == "nt":
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(2)

import tree_sitter_python
from tree_sitter import Language, Parser

source = "".join(
    f"def function_{index}(value):\n"
    "    result = value + 1\n"
    "    if result:\n"
    "        result += 2\n"
    "    return result\n\n"
    for index in range(200)
).encode()
line_starts = [0] + [index + 1 for index, byte in enumerate(source) if byte == 10]
parser = Parser(Language(tree_sitter_python.language()))
for _ in range(3):
    tree = parser.parse(source)
    assert not tree.root_node.has_error
    pending = [tree.root_node]
    while pending:
        node = pending.pop()
        start, end = node.start_point, node.end_point
        assert line_starts[start.row] + start.column == node.start_byte
        assert line_starts[end.row] + end.column == node.end_byte
        pending.extend(node.children)
print("coordinate reads complete", flush=True)
"""
    result = subprocess.run(  # noqa: S603 - fixed interpreter and dependency-only probe
        [sys.executable, "-X", "faulthandler", "-c", script],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "coordinate reads complete"
