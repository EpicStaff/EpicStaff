import os
import time
from pathlib import Path

from custom_tools import GlobTool
from tests.conftest import test_dir
from tests.tools_tests.new_tools_fixtures import glob_tool


def _touch_with_mtime(path: Path, mtime: float, content: str = "content") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    os.utime(path, (mtime, mtime))


class TestGlobTool:
    def test_glob_nested_tree_returns_newest_first(self, glob_tool: GlobTool):
        base = time.time()

        oldest = Path(test_dir) / "a.py"
        middle = Path(test_dir) / "sub" / "b.py"
        newest = Path(test_dir) / "sub" / "deeper" / "c.py"

        _touch_with_mtime(oldest, base - 200)
        _touch_with_mtime(middle, base - 100)
        _touch_with_mtime(newest, base)

        result = glob_tool._run(pattern="**/*.py")

        lines = result.splitlines()
        assert lines == [
            str(Path("sub") / "deeper" / "c.py"),
            str(Path("sub") / "b.py"),
            "a.py",
        ]

    def test_glob_directories_excluded(self, glob_tool: GlobTool):
        (Path(test_dir) / "dir.py").mkdir()
        _touch_with_mtime(Path(test_dir) / "file.py", time.time())

        result = glob_tool._run(pattern="*.py")

        assert result == "file.py"

    def test_glob_no_matches_returns_friendly_message_not_error(
        self, glob_tool: GlobTool
    ):
        result = glob_tool._run(pattern="**/*.csv")

        assert result == "No files match pattern **/*.csv"
        assert not result.startswith("Error:")

    def test_glob_cap_message_when_over_100_matches(self, glob_tool: GlobTool):
        base = time.time()
        for i in range(120):
            _touch_with_mtime(Path(test_dir) / f"file_{i:03d}.txt", base - i)

        result = glob_tool._run(pattern="*.txt")

        lines = result.splitlines()
        assert len(lines) == 101
        assert "(showing 100 of 120 matches — narrow the pattern)" in lines[-1]

    def test_glob_path_escape_returns_permission_error_no_exception(
        self, glob_tool: GlobTool
    ):
        result = glob_tool._run(pattern="*.py", path="../../etc")

        assert result.startswith("Error:")
        assert "outside the allowed directory" in result

    def test_glob_missing_pattern_returns_error(self, glob_tool: GlobTool):
        result = glob_tool._run()

        assert result.startswith("Error:")
        assert "pattern" in result

    def test_glob_scoped_to_subdirectory(self, glob_tool: GlobTool):
        _touch_with_mtime(Path(test_dir) / "top.py", time.time())
        _touch_with_mtime(Path(test_dir) / "sub" / "nested.py", time.time())

        result = glob_tool._run(pattern="*.py", path="sub")

        assert result == "nested.py"
