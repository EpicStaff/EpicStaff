"""Shared test infrastructure for the built-in python-code tools under
`src/shared/tools/`.

Each tool directory ships a standalone `main.py` (no package imports between
tools — only `main.py`'s source text is uploaded and executed by the
sandbox), so tests import each `main.py` directly by file path via
`importlib`, exactly as the sandbox loads it (as a bare module, not part of
the `shared.tools` package).
"""

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

TOOLS_ROOT = Path(__file__).resolve().parent.parent


def load_tool_main(tool_dir_name: str) -> ModuleType:
    """Import a tool's main.py as an isolated module, e.g. load_tool_main("read_file_tool")."""
    main_path = TOOLS_ROOT / tool_dir_name / "main.py"
    module_name = f"_shared_tool_{tool_dir_name}_main"

    spec = importlib.util.spec_from_file_location(module_name, main_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sandbox_dir(tmp_path, monkeypatch):
    """Point CONTAINER_SAVEFILES_PATH at an isolated temp directory, mirroring
    the sandbox's savefiles/ cwd convention used by RouteTool in each main.py."""
    monkeypatch.setenv("CONTAINER_SAVEFILES_PATH", str(tmp_path))
    return tmp_path
