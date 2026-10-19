"""Regression coverage for the sandbox code-assembly SyntaxError class of bug.

Sandbox-executed python-code tools don't run `main.py` verbatim. The sandbox
(`src/sandbox/dynamic_venv_executor_chain.py::ExecuteCodeHandler.wrap_code()`,
~lines 224-273) indents the tool source by 4 spaces and splices it inside a
`try:` block that already has `import sys` / `import json` / a `dotdict`
import ahead of it — see the `wrapped_code` f-string assembly around
lines 237-256. Python requires a `from __future__` import to be the very
first statement in a module (only a docstring may precede it); prepending
*anything* ahead of it — even a single `import sys` — turns it into a
`SyntaxError: from __future__ imports must occur at the beginning of the
file` at exec time inside the sandbox container. This bit `s3_bash_tool`,
whose `main.py` opened with `from __future__ import annotations`.

The rest of this suite (`conftest.load_tool`) imports each tool's `main.py`
directly by file path via `importlib`, which never exercises this assembly
step — that's exactly why the bug shipped undetected. These tests close that
gap by simulating the real sandbox wrapping for every tool `main.py` under
`src/shared/tools/`.
"""

from pathlib import Path

import pytest

from conftest import TOOLS_ROOT

_TOOL_MAIN_FILES = sorted(TOOLS_ROOT.glob("*/main.py"))
_TOOL_IDS = [p.parent.name for p in _TOOL_MAIN_FILES]

# Mirrors the real header ExecuteCodeHandler.wrap_code() prepends ahead of
# the (4-space-indented) tool body. See
# src/sandbox/dynamic_venv_executor_chain.py:237-248.
_SANDBOX_HEADER = (
    "import sys\n"
    "import json\n"
    "\n"
    "try:\n"
    "    from dotdict import DotDict, DotObject, DotList\n"
    "    for k, v in {}.items():\n"
    "        globals()[k] = v\n"
    "\n"
)
# Mirrors wrap_code()'s tail: the entrypoint call + result write + except
# clause that closes the try block the tool body was spliced into.
_SANDBOX_FOOTER = (
    "\n\n"
    "    pass\n"
    "except Exception as e:\n"
    "    print(str(e), file=sys.stderr)\n"
    "    sys.exit(1)\n"
)


def _indent(source: str) -> str:
    """Mirrors wrap_code()'s `code_lines = ['    ' + line for line in ...]`."""
    return "\n".join("    " + line for line in source.split("\n"))


@pytest.mark.parametrize("main_path", _TOOL_MAIN_FILES, ids=_TOOL_IDS)
def test_tool_main_compiles_with_sandbox_header_prepended(main_path: Path) -> None:
    """Simulates the real sandbox assembly (ExecuteCodeHandler.wrap_code) and
    asserts the combined source still compiles. This is the check that
    actually catches the s3_bash_tool class of bug — importing main.py
    directly by path, as the rest of this suite does, never exercises the
    sandbox's boilerplate-prepend step. A `from __future__` import anywhere in a
    tool fails here too: after the header it is no longer the first statement."""
    source = main_path.read_text(encoding="utf-8")
    wrapped = _SANDBOX_HEADER + _indent(source) + _SANDBOX_FOOTER
    compile(wrapped, f"<sandbox:{main_path.parent.name}/code.py>", "exec")
