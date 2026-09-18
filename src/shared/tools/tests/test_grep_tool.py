from pathlib import Path

from conftest import load_tool_main

grep_main = load_tool_main("grep_tool").main


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestGrepTool:
    """The sandbox has no `rg` binary available, so this tool has only the
    pure-Python backend — no branching/mocking needed."""

    def test_files_with_matches_default_mode(self, sandbox_dir):
        _write(sandbox_dir / "a.txt", "hello world\nfoo bar\n")
        _write(sandbox_dir / "b.txt", "nothing here\n")
        _write(sandbox_dir / "sub" / "c.txt", "hello again\n")

        result = grep_main(pattern="hello")

        lines = set(result.splitlines())
        assert lines == {"a.txt", str(Path("sub") / "c.txt")}

    def test_content_mode_with_context_lines(self, sandbox_dir):
        content = "\n".join(f"line{i}" for i in range(1, 11))
        _write(sandbox_dir / "doc.txt", content)

        result = grep_main(pattern="line5", output_mode="content", context_lines=2)

        lines = result.splitlines()
        assert lines == [
            "doc.txt:3:line3",
            "doc.txt:4:line4",
            "doc.txt:5:line5",
            "doc.txt:6:line6",
            "doc.txt:7:line7",
        ]

    def test_count_mode_totals(self, sandbox_dir):
        _write(sandbox_dir / "a.txt", "cat\ncat\ndog\ncat\n")
        _write(sandbox_dir / "b.txt", "cat\n")

        result = grep_main(pattern="cat", output_mode="count")

        lines = result.splitlines()
        assert "a.txt:3" in lines
        assert "b.txt:1" in lines
        assert "total:4" in lines

    def test_glob_filter(self, sandbox_dir):
        _write(sandbox_dir / "match.log", "needle here\n")
        _write(sandbox_dir / "match.txt", "needle here\n")

        result = grep_main(pattern="needle", glob="*.log")

        assert result == "match.log"

    def test_glob_filter_matches_path_style_pattern(self, sandbox_dir):
        _write(sandbox_dir / "sub" / "match.py", "needle here\n")
        _write(sandbox_dir / "match.py", "needle here\n")

        result = grep_main(pattern="needle", glob="sub/*.py")

        assert result == str(Path("sub") / "match.py")

    def test_invalid_regex_returns_readable_error_no_traceback(self, sandbox_dir):
        _write(sandbox_dir / "a.txt", "content\n")

        result = grep_main(pattern="(")

        assert result.startswith("Error: invalid regex")
        assert "Traceback" not in result

    def test_head_limit_truncation_announced(self, sandbox_dir):
        content = "\n".join("needle" for _ in range(20))
        _write(sandbox_dir / "many.txt", content)

        result = grep_main(pattern="needle", output_mode="content", head_limit=5)

        lines = result.splitlines()
        assert len(lines) == 6
        assert "showing first 5 of 20 lines" in lines[-1]

    def test_no_matches_returns_friendly_message(self, sandbox_dir):
        _write(sandbox_dir / "a.txt", "nothing interesting\n")

        result = grep_main(pattern="zzzznomatch")

        assert result == "No matches for pattern zzzznomatch"

    def test_path_escape_returns_permission_error_no_exception(self, sandbox_dir):
        result = grep_main(pattern="anything", path="../../etc")

        assert result.startswith("Error:")
        assert "outside the allowed directory" in result

    def test_case_insensitive_search(self, sandbox_dir):
        _write(sandbox_dir / "a.txt", "Hello World\n")

        result = grep_main(pattern="hello world", case_insensitive=True)

        assert result == "a.txt"

    def test_missing_pattern_returns_error(self, sandbox_dir):
        result = grep_main(pattern="")

        assert result.startswith("Error:")
        assert "pattern" in result
