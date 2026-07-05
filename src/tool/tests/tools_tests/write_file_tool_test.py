from pathlib import Path

from custom_tools import WriteFileTool
from tests.conftest import test_dir
from tests.tools_tests.new_tools_fixtures import write_file_tool


class TestWriteFileTool:
    def test_write_new_file(self, write_file_tool: WriteFileTool):
        result = write_file_tool._run(file_path="new.txt", content="hello world")

        written_path = Path(test_dir) / "new.txt"
        assert written_path.read_text() == "hello world"
        assert result == f"File written: new.txt ({len('hello world'.encode())} bytes)"

    def test_write_creates_parent_directories(self, write_file_tool: WriteFileTool):
        result = write_file_tool._run(
            file_path="nested/dir/new.txt", content="nested content"
        )

        written_path = Path(test_dir) / "nested" / "dir" / "new.txt"
        assert written_path.exists()
        assert written_path.read_text() == "nested content"
        assert result.startswith("File written: nested/dir/new.txt")

    def test_double_write_without_overwrite_fails_then_succeeds_with_flag(
        self, write_file_tool: WriteFileTool
    ):
        first = write_file_tool._run(file_path="dup.txt", content="v1")
        assert first.startswith("File written:")

        second = write_file_tool._run(file_path="dup.txt", content="v2")
        assert second.startswith("Error:")
        assert "overwrite=true" in second
        assert (Path(test_dir) / "dup.txt").read_text() == "v1"

        third = write_file_tool._run(file_path="dup.txt", content="v2", overwrite=True)
        assert third.startswith("File written:")
        assert (Path(test_dir) / "dup.txt").read_text() == "v2"

    def test_write_content_exceeding_cap_returns_error(
        self, write_file_tool: WriteFileTool
    ):
        too_big_content = "a" * (1024 * 1024 + 1)

        result = write_file_tool._run(file_path="huge.txt", content=too_big_content)

        assert result.startswith("Error:")
        assert "byte cap" in result
        assert not (Path(test_dir) / "huge.txt").exists()

    def test_write_path_escape_returns_permission_error_no_exception(
        self, write_file_tool: WriteFileTool
    ):
        result = write_file_tool._run(
            file_path="../../etc/passwd", content="malicious"
        )

        assert result.startswith("Error:")
        assert "outside the allowed directory" in result

    def test_write_missing_file_path_returns_error(self, write_file_tool: WriteFileTool):
        result = write_file_tool._run(content="no path given")

        assert result.startswith("Error:")
        assert "file_path" in result
