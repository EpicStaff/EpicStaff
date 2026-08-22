from conftest import load_tool_main

string_edit_main = load_tool_main("string_edit_tool").main


class TestStringEditTool:
    def test_replace_single_occurrence(self, sandbox_dir):
        (sandbox_dir / "edit.txt").write_text("hello world\ngoodbye world")

        result = string_edit_main(
            file_path="edit.txt", old_string="hello world", new_string="hi world"
        )

        assert result.startswith("Replaced 1 occurrence(s) in edit.txt")
        assert (sandbox_dir / "edit.txt").read_text() == "hi world\ngoodbye world"

    def test_replace_all_occurrences(self, sandbox_dir):
        (sandbox_dir / "edit_all.txt").write_text("foo bar foo baz foo")

        result = string_edit_main(
            file_path="edit_all.txt",
            old_string="foo",
            new_string="qux",
            replace_all=True,
        )

        assert result.startswith("Replaced 3 occurrence(s) in edit_all.txt")
        assert (sandbox_dir / "edit_all.txt").read_text() == "qux bar qux baz qux"

    def test_old_string_not_found_returns_error(self, sandbox_dir):
        original = "hello world"
        (sandbox_dir / "edit.txt").write_text(original)

        result = string_edit_main(
            file_path="edit.txt", old_string="not there", new_string="x"
        )

        assert result == "Error: old_string not found in edit.txt."
        assert (sandbox_dir / "edit.txt").read_text() == original

    def test_ambiguous_old_string_without_replace_all_errors_and_leaves_file_unchanged(
        self, sandbox_dir
    ):
        original = "duplicate line\nother line\nduplicate line"
        (sandbox_dir / "ambiguous.txt").write_text(original)

        result = string_edit_main(
            file_path="ambiguous.txt", old_string="duplicate line", new_string="changed"
        )

        assert result.startswith("Error:")
        assert "2 locations" in result
        assert (sandbox_dir / "ambiguous.txt").read_text() == original

    def test_new_string_must_differ_from_old_string(self, sandbox_dir):
        (sandbox_dir / "same.txt").write_text("content")

        result = string_edit_main(
            file_path="same.txt", old_string="content", new_string="content"
        )

        assert result.startswith("Error:")
        assert "must differ" in result

    def test_crlf_line_endings_are_preserved(self, sandbox_dir):
        (sandbox_dir / "crlf.txt").write_bytes(b"line one\r\nline two\r\nline three")

        result = string_edit_main(
            file_path="crlf.txt", old_string="line two", new_string="LINE TWO"
        )

        assert result.startswith("Replaced 1 occurrence(s)")
        raw = (sandbox_dir / "crlf.txt").read_bytes()
        assert raw == b"line one\r\nLINE TWO\r\nline three"

    def test_multiline_old_string(self, sandbox_dir):
        (sandbox_dir / "multiline.txt").write_text("a\nb\nc\nd")

        result = string_edit_main(
            file_path="multiline.txt", old_string="b\nc", new_string="B\nC\nX"
        )

        assert result.startswith("Replaced 1 occurrence(s)")
        assert (sandbox_dir / "multiline.txt").read_text() == "a\nB\nC\nX\nd"

    def test_missing_file_returns_error(self, sandbox_dir):
        result = string_edit_main(
            file_path="missing.txt", old_string="a", new_string="b"
        )

        assert result.startswith("Error:")
        assert "does not exist" in result

    def test_path_escape_returns_permission_error_no_exception(self, sandbox_dir):
        result = string_edit_main(
            file_path="../../etc/passwd", old_string="root", new_string="hacked"
        )

        assert result.startswith("Error:")
        assert "outside the allowed directory" in result
