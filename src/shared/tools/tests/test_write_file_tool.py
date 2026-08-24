from conftest import load_tool_main

write_file_main = load_tool_main("write_file_tool").main


class TestWriteFileTool:
    def test_write_new_file(self, sandbox_dir):
        result = write_file_main(file_path="new.txt", content="hello world")

        written_path = sandbox_dir / "new.txt"
        assert written_path.read_text() == "hello world"
        assert result == f"File written: new.txt ({len('hello world'.encode())} bytes)"

    def test_write_creates_parent_directories(self, sandbox_dir):
        result = write_file_main(file_path="nested/dir/new.txt", content="nested content")

        written_path = sandbox_dir / "nested" / "dir" / "new.txt"
        assert written_path.exists()
        assert written_path.read_text() == "nested content"
        assert result.startswith("File written: nested/dir/new.txt") or result.startswith(
            "File written: nested\\dir\\new.txt"
        )

    def test_double_write_without_overwrite_fails_then_succeeds_with_flag(self, sandbox_dir):
        first = write_file_main(file_path="dup.txt", content="v1")
        assert first.startswith("File written:")

        second = write_file_main(file_path="dup.txt", content="v2")
        assert second.startswith("Error:")
        assert "overwrite=true" in second
        assert (sandbox_dir / "dup.txt").read_text() == "v1"

        third = write_file_main(file_path="dup.txt", content="v2", overwrite=True)
        assert third.startswith("File written:")
        assert (sandbox_dir / "dup.txt").read_text() == "v2"

    def test_write_content_exceeding_cap_returns_error(self, sandbox_dir):
        too_big_content = "a" * (1024 * 1024 + 1)

        result = write_file_main(file_path="huge.txt", content=too_big_content)

        assert result.startswith("Error:")
        assert "byte cap" in result
        assert not (sandbox_dir / "huge.txt").exists()

    def test_write_path_escape_returns_permission_error_no_exception(self, sandbox_dir):
        result = write_file_main(file_path="../../etc/passwd", content="malicious")

        assert result.startswith("Error:")
        assert "outside the allowed directory" in result

    def test_write_missing_content_returns_error(self, sandbox_dir):
        result = write_file_main(file_path="no_content.txt", content=None)

        assert result.startswith("Error:")
        assert "content" in result
