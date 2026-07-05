"""Fixtures for the Phase 1 tool-library-parity tools (EST-3285).

Kept separate from `fixtures.py` because that module imports `CLITool`, which
is currently broken (`interpreter_tool` import is commented out in
`custom_tools/__init__.py`), which would otherwise break collection of these
test modules too.
"""

from pathlib import Path
from shutil import rmtree

import pytest

from custom_tools import (
    ReadFileTool,
    WriteFileTool,
    StringEditTool,
    NotebookEditTool,
    GlobTool,
    GrepTool,
)
from tests.conftest import test_dir


@pytest.fixture
def read_file_tool(monkeypatch):
    path = Path(test_dir)
    path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SAVE_FILE_PATH", test_dir)

    yield ReadFileTool()

    rmtree(path)


@pytest.fixture
def write_file_tool(monkeypatch):
    path = Path(test_dir)
    path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SAVE_FILE_PATH", test_dir)

    yield WriteFileTool()

    rmtree(path)


@pytest.fixture
def string_edit_tool(monkeypatch):
    path = Path(test_dir)
    path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SAVE_FILE_PATH", test_dir)

    yield StringEditTool()

    rmtree(path)


@pytest.fixture
def notebook_edit_tool(monkeypatch):
    path = Path(test_dir)
    path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SAVE_FILE_PATH", test_dir)

    yield NotebookEditTool()

    rmtree(path)


@pytest.fixture
def glob_tool(monkeypatch):
    path = Path(test_dir)
    path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SAVE_FILE_PATH", test_dir)

    yield GlobTool()

    rmtree(path)


@pytest.fixture
def grep_tool(monkeypatch):
    path = Path(test_dir)
    path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SAVE_FILE_PATH", test_dir)

    yield GrepTool()

    rmtree(path)
