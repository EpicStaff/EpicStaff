from pathlib import Path

import pytest

from conftest import load_tool_main
from mocks.pdf_builder import build_minimal_pdf

pytest.importorskip("pypdfium2")
pytest.importorskip("nbformat")

read_file_main = load_tool_main("read_file_tool").main


class TestReadFileTool:
    def test_read_text_happy_path(self, sandbox_dir):
        (sandbox_dir / "hello.txt").write_text("line one\nline two\nline three")

        result = read_file_main(file_path="hello.txt")

        assert result == "     1\tline one\n     2\tline two\n     3\tline three"

    def test_read_text_with_offset_and_limit(self, sandbox_dir):
        (sandbox_dir / "offset.txt").write_text(
            "\n".join(f"line{i}" for i in range(1, 11))
        )

        result = read_file_main(file_path="offset.txt", offset=3, limit=2)

        lines = result.splitlines()
        assert lines[0] == "     3\tline3"
        assert lines[1] == "     4\tline4"
        assert "showing lines 3-4 of 10" in result

    def test_read_text_truncates_5000_line_file_without_offset(self, sandbox_dir):
        (sandbox_dir / "big.txt").write_text(
            "\n".join(f"line{i}" for i in range(1, 5001))
        )

        result = read_file_main(file_path="big.txt")

        lines = result.splitlines()
        assert len(lines) == 2001
        assert lines[0] == "     1\tline1"
        assert lines[1999] == "  2000\tline2000"
        assert "showing lines 1-2000 of 5000" in lines[2000]
        assert "truncated" in lines[2000]

    def test_read_text_long_line_is_truncated_with_marker(self, sandbox_dir):
        long_line = "x" * 3000
        (sandbox_dir / "longline.txt").write_text(long_line)

        result = read_file_main(file_path="longline.txt")

        assert result.endswith("…")
        content_only = result.split("\t", 1)[1]
        assert len(content_only) == 2001

    def test_read_empty_file(self, sandbox_dir):
        (sandbox_dir / "empty.txt").touch()

        result = read_file_main(file_path="empty.txt")

        assert result == "Warning: file exists but is empty"

    def test_read_directory_returns_error(self, sandbox_dir):
        (sandbox_dir / "some_dir").mkdir()

        result = read_file_main(file_path="some_dir")

        assert result.startswith("Error:")
        assert "directory" in result
        assert "GlobTool" in result or "FolderTool" in result

    def test_read_missing_file_returns_error(self, sandbox_dir):
        result = read_file_main(file_path="does_not_exist.txt")

        assert result.startswith("Error:")
        assert "does not exist" in result

    def test_read_missing_file_suggests_similar_name(self, sandbox_dir):
        (sandbox_dir / "report.txt").write_text("content")

        result = read_file_main(file_path="report.tx")

        assert result.startswith("Error:")
        assert "report.txt" in result

    def test_read_path_escape_returns_permission_error_no_exception(self, sandbox_dir):
        result = read_file_main(file_path="../../etc/passwd")

        assert result.startswith("Error:")
        assert "outside the allowed directory" in result

    def test_read_pdf_specific_page(self, sandbox_dir):
        pdf_bytes = build_minimal_pdf([f"page {i} content" for i in range(1, 51)])
        (sandbox_dir / "report.pdf").write_bytes(pdf_bytes)

        result = read_file_main(file_path="report.pdf", pages="3")

        assert result == "=== page 3 ===\npage 3 content"

    def test_read_pdf_requires_pages_when_over_ten_pages(self, sandbox_dir):
        pdf_bytes = build_minimal_pdf([f"page {i} content" for i in range(1, 51)])
        (sandbox_dir / "report.pdf").write_bytes(pdf_bytes)

        result = read_file_main(file_path="report.pdf")

        assert result.startswith("Error:")
        assert "pages" in result

    def test_read_pdf_page_range(self, sandbox_dir):
        pdf_bytes = build_minimal_pdf([f"page {i} content" for i in range(1, 6)])
        (sandbox_dir / "small.pdf").write_bytes(pdf_bytes)

        result = read_file_main(file_path="small.pdf", pages="2-3")

        assert "=== page 2 ===\npage 2 content" in result
        assert "=== page 3 ===\npage 3 content" in result
        assert "page 1" not in result

    def test_read_pdf_small_document_without_pages_arg(self, sandbox_dir):
        pdf_bytes = build_minimal_pdf([f"page {i} content" for i in range(1, 4)])
        (sandbox_dir / "small.pdf").write_bytes(pdf_bytes)

        result = read_file_main(file_path="small.pdf")

        assert "=== page 1 ===" in result
        assert "=== page 2 ===" in result
        assert "=== page 3 ===" in result

    def test_read_notebook(self, sandbox_dir):
        import nbformat
        from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

        nb = new_notebook(
            cells=[
                new_code_cell(source="print('hi')"),
                new_markdown_cell(source="# Title"),
            ]
        )
        nbformat.write(nb, str(sandbox_dir / "notebook.ipynb"))

        result = read_file_main(file_path="notebook.ipynb")

        assert "[cell 0: code]" in result
        assert "print('hi')" in result
        assert "[cell 1: markdown]" in result
        assert "# Title" in result
