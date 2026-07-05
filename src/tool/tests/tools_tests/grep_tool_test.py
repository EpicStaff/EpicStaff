import shutil
from pathlib import Path

import pytest

from custom_tools import GrepTool
from tests.conftest import test_dir
from tests.tools_tests.new_tools_fixtures import grep_tool

RG_AVAILABLE = shutil.which("rg") is not None


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestGrepToolPythonFallback:
    """Exercises the pure-Python backend by forcing shutil.which('rg') to
    return None, regardless of whether rg is actually installed locally."""

    @pytest.fixture(autouse=True)
    def _force_fallback(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: None)

    def test_files_with_matches_default_mode(self, grep_tool: GrepTool):
        _write(Path(test_dir) / "a.txt", "hello world\nfoo bar\n")
        _write(Path(test_dir) / "b.txt", "nothing here\n")
        _write(Path(test_dir) / "sub" / "c.txt", "hello again\n")

        result = grep_tool._run(pattern="hello")

        lines = set(result.splitlines())
        assert lines == {"a.txt", str(Path("sub") / "c.txt")}

    def test_content_mode_with_context_lines(self, grep_tool: GrepTool):
        content = "\n".join(f"line{i}" for i in range(1, 11))
        _write(Path(test_dir) / "doc.txt", content)

        result = grep_tool._run(
            pattern="line5", output_mode="content", context_lines=2
        )

        lines = result.splitlines()
        assert lines == [
            "doc.txt:3:line3",
            "doc.txt:4:line4",
            "doc.txt:5:line5",
            "doc.txt:6:line6",
            "doc.txt:7:line7",
        ]

    def test_count_mode_totals(self, grep_tool: GrepTool):
        _write(Path(test_dir) / "a.txt", "cat\ncat\ndog\ncat\n")
        _write(Path(test_dir) / "b.txt", "cat\n")

        result = grep_tool._run(pattern="cat", output_mode="count")

        lines = result.splitlines()
        assert "a.txt:3" in lines
        assert "b.txt:1" in lines
        assert "total:4" in lines

    def test_glob_filter(self, grep_tool: GrepTool):
        _write(Path(test_dir) / "match.log", "needle here\n")
        _write(Path(test_dir) / "match.txt", "needle here\n")

        result = grep_tool._run(pattern="needle", glob="*.log")

        assert result == "match.log"

    def test_invalid_regex_returns_readable_error_no_traceback(
        self, grep_tool: GrepTool
    ):
        _write(Path(test_dir) / "a.txt", "content\n")

        result = grep_tool._run(pattern="(")

        assert result.startswith("Error: invalid regex")
        assert "Traceback" not in result

    def test_head_limit_truncation_announced(self, grep_tool: GrepTool):
        content = "\n".join("needle" for _ in range(20))
        _write(Path(test_dir) / "many.txt", content)

        result = grep_tool._run(
            pattern="needle", output_mode="content", head_limit=5
        )

        lines = result.splitlines()
        assert len(lines) == 6
        assert "showing first 5 of 20 lines" in lines[-1]

    def test_no_matches_returns_friendly_message(self, grep_tool: GrepTool):
        _write(Path(test_dir) / "a.txt", "nothing interesting\n")

        result = grep_tool._run(pattern="zzzznomatch")

        assert result == "No matches for pattern zzzznomatch"

    def test_path_escape_returns_permission_error_no_exception(
        self, grep_tool: GrepTool
    ):
        result = grep_tool._run(pattern="anything", path="../../etc")

        assert result.startswith("Error:")
        assert "outside the allowed directory" in result

    def test_case_insensitive_search(self, grep_tool: GrepTool):
        _write(Path(test_dir) / "a.txt", "Hello World\n")

        result = grep_tool._run(pattern="hello world", case_insensitive=True)

        assert result == "a.txt"

    def test_missing_pattern_returns_error(self, grep_tool: GrepTool):
        result = grep_tool._run()

        assert result.startswith("Error:")
        assert "pattern" in result


@pytest.mark.skipif(not RG_AVAILABLE, reason="ripgrep not installed on this machine")
class TestGrepToolRipgrepBackend:
    """Same behavioral contract, exercised against the real rg binary."""

    def test_files_with_matches_default_mode(self, grep_tool: GrepTool):
        _write(Path(test_dir) / "a.txt", "hello world\nfoo bar\n")
        _write(Path(test_dir) / "b.txt", "nothing here\n")
        _write(Path(test_dir) / "sub" / "c.txt", "hello again\n")

        result = grep_tool._run(pattern="hello")

        lines = set(result.splitlines())
        assert lines == {"a.txt", str(Path("sub") / "c.txt")}

    def test_content_mode_with_context_lines(self, grep_tool: GrepTool):
        content = "\n".join(f"line{i}" for i in range(1, 11))
        _write(Path(test_dir) / "doc.txt", content)

        result = grep_tool._run(
            pattern="line5", output_mode="content", context_lines=2
        )

        lines = result.splitlines()
        assert lines == [
            "doc.txt:3:line3",
            "doc.txt:4:line4",
            "doc.txt:5:line5",
            "doc.txt:6:line6",
            "doc.txt:7:line7",
        ]

    def test_count_mode_totals(self, grep_tool: GrepTool):
        _write(Path(test_dir) / "a.txt", "cat\ncat\ndog\ncat\n")
        _write(Path(test_dir) / "b.txt", "cat\n")

        result = grep_tool._run(pattern="cat", output_mode="count")

        lines = result.splitlines()
        assert "a.txt:3" in lines
        assert "b.txt:1" in lines
        assert "total:4" in lines

    def test_invalid_regex_returns_readable_error_no_traceback(
        self, grep_tool: GrepTool
    ):
        _write(Path(test_dir) / "a.txt", "content\n")

        result = grep_tool._run(pattern="(")

        assert result.startswith("Error: invalid regex")
        assert "Traceback" not in result
