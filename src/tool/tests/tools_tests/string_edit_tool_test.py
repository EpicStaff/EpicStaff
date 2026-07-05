from pathlib import Path

from custom_tools import StringEditTool
from tests.conftest import test_dir
from tests.tools_tests.new_tools_fixtures import string_edit_tool


class TestStringEditTool:
    def test_replace_single_occurrence(self, string_edit_tool: StringEditTool):
        file_path = "edit.txt"
        (Path(test_dir) / file_path).write_text("hello world\ngoodbye world")

        result = string_edit_tool._run(
            file_path=file_path, old_string="hello world", new_string="hi world"
        )

        assert result.startswith("Replaced 1 occurrence(s) in edit.txt")
        assert (Path(test_dir) / file_path).read_text() == "hi world\ngoodbye world"

    def test_replace_all_occurrences(self, string_edit_tool: StringEditTool):
        file_path = "edit_all.txt"
        (Path(test_dir) / file_path).write_text("foo bar foo baz foo")

        result = string_edit_tool._run(
            file_path=file_path,
            old_string="foo",
            new_string="qux",
            replace_all=True,
        )

        assert result.startswith("Replaced 3 occurrence(s) in edit_all.txt")
        assert (Path(test_dir) / file_path).read_text() == "qux bar qux baz qux"

    def test_old_string_not_found_returns_error(self, string_edit_tool: StringEditTool):
        file_path = "edit.txt"
        original = "hello world"
        (Path(test_dir) / file_path).write_text(original)

        result = string_edit_tool._run(
            file_path=file_path, old_string="not there", new_string="x"
        )

        assert result == f"Error: old_string not found in {file_path}."
        assert (Path(test_dir) / file_path).read_text() == original

    def test_ambiguous_old_string_without_replace_all_errors_and_leaves_file_unchanged(
        self, string_edit_tool: StringEditTool
    ):
        file_path = "ambiguous.txt"
        original = "duplicate line\nother line\nduplicate line"
        (Path(test_dir) / file_path).write_text(original)

        result = string_edit_tool._run(
            file_path=file_path, old_string="duplicate line", new_string="changed"
        )

        assert result.startswith("Error:")
        assert "2 locations" in result
        assert (Path(test_dir) / file_path).read_text() == original

    def test_new_string_must_differ_from_old_string(
        self, string_edit_tool: StringEditTool
    ):
        file_path = "same.txt"
        (Path(test_dir) / file_path).write_text("content")

        result = string_edit_tool._run(
            file_path=file_path, old_string="content", new_string="content"
        )

        assert result.startswith("Error:")
        assert "must differ" in result

    def test_crlf_line_endings_are_preserved(self, string_edit_tool: StringEditTool):
        file_path = "crlf.txt"
        with open(Path(test_dir) / file_path, "wb") as f:
            f.write(b"line one\r\nline two\r\nline three")

        result = string_edit_tool._run(
            file_path=file_path, old_string="line two", new_string="LINE TWO"
        )

        assert result.startswith("Replaced 1 occurrence(s)")
        raw = (Path(test_dir) / file_path).read_bytes()
        assert raw == b"line one\r\nLINE TWO\r\nline three"

    def test_multiline_old_string(self, string_edit_tool: StringEditTool):
        file_path = "multiline.txt"
        (Path(test_dir) / file_path).write_text("a\nb\nc\nd")

        result = string_edit_tool._run(
            file_path=file_path, old_string="b\nc", new_string="B\nC\nX"
        )

        assert result.startswith("Replaced 1 occurrence(s)")
        assert (Path(test_dir) / file_path).read_text() == "a\nB\nC\nX\nd"

    def test_missing_file_returns_error(self, string_edit_tool: StringEditTool):
        result = string_edit_tool._run(
            file_path="missing.txt", old_string="a", new_string="b"
        )

        assert result.startswith("Error:")
        assert "does not exist" in result

    def test_path_escape_returns_permission_error_no_exception(
        self, string_edit_tool: StringEditTool
    ):
        result = string_edit_tool._run(
            file_path="../../etc/passwd", old_string="root", new_string="hacked"
        )

        assert result.startswith("Error:")
        assert "outside the allowed directory" in result
