from pathlib import Path

import pytest

from custom_tools import ReadFileTool
from tests.conftest import test_dir
from tests.tools_tests.new_tools_fixtures import read_file_tool
from tests.tools_tests.mocks.pdf_builder import build_minimal_pdf

pytest.importorskip("pypdfium2")
pytest.importorskip("nbformat")


class TestReadFileTool:
    def test_read_text_happy_path(self, read_file_tool: ReadFileTool):
        file_path = "hello.txt"
        with open(Path(test_dir) / file_path, "w") as f:
            f.write("line one\nline two\nline three")

        result = read_file_tool._run(file_path=file_path)

        assert result == "     1\tline one\n     2\tline two\n     3\tline three"

    def test_read_text_with_offset_and_limit(self, read_file_tool: ReadFileTool):
        file_path = "offset.txt"
        with open(Path(test_dir) / file_path, "w") as f:
            f.write("\n".join(f"line{i}" for i in range(1, 11)))

        result = read_file_tool._run(file_path=file_path, offset=3, limit=2)

        lines = result.splitlines()
        assert lines[0] == "     3\tline3"
        assert lines[1] == "     4\tline4"
        assert "showing lines 3-4 of 10" in result

    def test_read_text_truncates_5000_line_file_without_offset(
        self, read_file_tool: ReadFileTool
    ):
        file_path = "big.txt"
        with open(Path(test_dir) / file_path, "w") as f:
            f.write("\n".join(f"line{i}" for i in range(1, 5001)))

        result = read_file_tool._run(file_path=file_path)

        lines = result.splitlines()
        # 2000 numbered lines + 1 truncation notice line
        assert len(lines) == 2001
        assert lines[0] == "     1\tline1"
        assert lines[1999] == "  2000\tline2000"
        assert "showing lines 1-2000 of 5000" in lines[2000]
        assert "truncated" in lines[2000]

    def test_read_text_long_line_is_truncated_with_marker(
        self, read_file_tool: ReadFileTool
    ):
        file_path = "longline.txt"
        long_line = "x" * 3000
        with open(Path(test_dir) / file_path, "w") as f:
            f.write(long_line)

        result = read_file_tool._run(file_path=file_path)

        assert result.endswith("…")
        # 2000 chars + the ellipsis marker
        content_only = result.split("\t", 1)[1]
        assert len(content_only) == 2001

    def test_read_empty_file(self, read_file_tool: ReadFileTool):
        file_path = "empty.txt"
        (Path(test_dir) / file_path).touch()

        result = read_file_tool._run(file_path=file_path)

        assert result == "Warning: file exists but is empty"

    def test_read_directory_returns_error(self, read_file_tool: ReadFileTool):
        dir_path = "some_dir"
        (Path(test_dir) / dir_path).mkdir()

        result = read_file_tool._run(file_path=dir_path)

        assert result.startswith("Error:")
        assert "directory" in result
        assert "GlobTool" in result or "FolderTool" in result

    def test_read_missing_file_returns_error(self, read_file_tool: ReadFileTool):
        result = read_file_tool._run(file_path="does_not_exist.txt")

        assert result.startswith("Error:")
        assert "does not exist" in result

    def test_read_missing_file_suggests_similar_name(self, read_file_tool: ReadFileTool):
        existing_path = Path(test_dir) / "report.txt"
        existing_path.write_text("content")

        result = read_file_tool._run(file_path="report.tx")

        assert result.startswith("Error:")
        assert "report.txt" in result

    def test_read_path_escape_returns_permission_error_no_exception(
        self, read_file_tool: ReadFileTool
    ):
        result = read_file_tool._run(file_path="../../etc/passwd")

        assert result.startswith("Error:")
        assert "outside the allowed directory" in result

    def test_read_pdf_specific_page(self, read_file_tool: ReadFileTool):
        pdf_bytes = build_minimal_pdf([f"page {i} content" for i in range(1, 51)])
        file_path = "report.pdf"
        (Path(test_dir) / file_path).write_bytes(pdf_bytes)

        result = read_file_tool._run(file_path=file_path, pages="3")

        assert result == "=== page 3 ===\npage 3 content"

    def test_read_pdf_requires_pages_when_over_ten_pages(
        self, read_file_tool: ReadFileTool
    ):
        pdf_bytes = build_minimal_pdf([f"page {i} content" for i in range(1, 51)])
        file_path = "report.pdf"
        (Path(test_dir) / file_path).write_bytes(pdf_bytes)

        result = read_file_tool._run(file_path=file_path)

        assert result.startswith("Error:")
        assert "pages" in result

    def test_read_pdf_page_range(self, read_file_tool: ReadFileTool):
        pdf_bytes = build_minimal_pdf([f"page {i} content" for i in range(1, 6)])
        file_path = "small.pdf"
        (Path(test_dir) / file_path).write_bytes(pdf_bytes)

        result = read_file_tool._run(file_path=file_path, pages="2-3")

        assert "=== page 2 ===\npage 2 content" in result
        assert "=== page 3 ===\npage 3 content" in result
        assert "page 1" not in result

    def test_read_pdf_small_document_without_pages_arg(
        self, read_file_tool: ReadFileTool
    ):
        pdf_bytes = build_minimal_pdf([f"page {i} content" for i in range(1, 4)])
        file_path = "small.pdf"
        (Path(test_dir) / file_path).write_bytes(pdf_bytes)

        result = read_file_tool._run(file_path=file_path)

        assert "=== page 1 ===" in result
        assert "=== page 2 ===" in result
        assert "=== page 3 ===" in result

    def test_read_notebook(self, read_file_tool: ReadFileTool):
        import nbformat
        from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

        nb = new_notebook(
            cells=[
                new_code_cell(source="print('hi')"),
                new_markdown_cell(source="# Title"),
            ]
        )
        file_path = "notebook.ipynb"
        nbformat.write(nb, str(Path(test_dir) / file_path))

        result = read_file_tool._run(file_path=file_path)

        assert "[cell 0: code]" in result
        assert "print('hi')" in result
        assert "[cell 1: markdown]" in result
        assert "# Title" in result
