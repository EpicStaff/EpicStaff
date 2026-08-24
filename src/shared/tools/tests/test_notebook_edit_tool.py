import pytest

from conftest import load_tool_main

pytest.importorskip("nbformat")

notebook_edit_main = load_tool_main("notebook_edit_tool").main


def _write_notebook(sandbox_dir, file_path: str, cell_sources):
    import nbformat
    from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

    cells = [
        new_code_cell(source=src) if cell_type == "code" else new_markdown_cell(source=src)
        for cell_type, src in cell_sources
    ]
    nb = new_notebook(cells=cells)
    nbformat.write(nb, str(sandbox_dir / file_path))
    return [cell.get("id") for cell in nb.cells]


def _read_notebook(sandbox_dir, file_path: str):
    import nbformat

    return nbformat.read(str(sandbox_dir / file_path), as_version=4)


class TestNotebookEditTool:
    def test_replace_cell(self, sandbox_dir):
        file_path = "nb.ipynb"
        cell_ids = _write_notebook(
            sandbox_dir, file_path, [("code", "print(1)"), ("markdown", "# Title")]
        )

        result = notebook_edit_main(
            notebook_path=file_path, new_source="print(2)", cell_id=cell_ids[0]
        )

        assert result == f"replace cell {cell_ids[0]} in {file_path}"

        nb = _read_notebook(sandbox_dir, file_path)
        assert nb.cells[0]["source"] == "print(2)"
        assert nb.cells[0]["outputs"] == []
        assert nb.cells[0]["execution_count"] is None

    def test_replace_missing_cell_id_lists_available_ids(self, sandbox_dir):
        file_path = "nb.ipynb"
        cell_ids = _write_notebook(sandbox_dir, file_path, [("code", "print(1)")])

        result = notebook_edit_main(
            notebook_path=file_path, new_source="print(2)", cell_id="does-not-exist"
        )

        assert result.startswith("Error:")
        assert "does-not-exist" in result
        assert cell_ids[0] in result

    def test_delete_cell(self, sandbox_dir):
        file_path = "nb.ipynb"
        cell_ids = _write_notebook(
            sandbox_dir, file_path, [("code", "print(1)"), ("code", "print(2)")]
        )

        result = notebook_edit_main(
            notebook_path=file_path,
            new_source="",
            cell_id=cell_ids[0],
            edit_mode="delete",
        )

        assert result == f"delete cell {cell_ids[0]} in {file_path}"
        nb = _read_notebook(sandbox_dir, file_path)
        assert len(nb.cells) == 1
        assert nb.cells[0]["source"] == "print(2)"

    def test_insert_cell_at_top_when_cell_id_omitted(self, sandbox_dir):
        file_path = "nb.ipynb"
        _write_notebook(sandbox_dir, file_path, [("code", "print(1)")])

        result = notebook_edit_main(
            notebook_path=file_path,
            new_source="# new top cell",
            cell_type="markdown",
            edit_mode="insert",
        )

        assert result.startswith("insert cell ")
        assert result.endswith(f"in {file_path}")

        nb = _read_notebook(sandbox_dir, file_path)
        assert len(nb.cells) == 2
        assert nb.cells[0]["source"] == "# new top cell"
        assert nb.cells[0]["cell_type"] == "markdown"
        assert nb.cells[1]["source"] == "print(1)"

    def test_insert_cell_after_given_cell_id(self, sandbox_dir):
        file_path = "nb.ipynb"
        cell_ids = _write_notebook(
            sandbox_dir, file_path, [("code", "print(1)"), ("code", "print(2)")]
        )

        result = notebook_edit_main(
            notebook_path=file_path,
            new_source="print(1.5)",
            cell_id=cell_ids[0],
            cell_type="code",
            edit_mode="insert",
        )

        assert result.startswith("insert cell")
        nb = _read_notebook(sandbox_dir, file_path)
        assert len(nb.cells) == 3
        assert nb.cells[0]["source"] == "print(1)"
        assert nb.cells[1]["source"] == "print(1.5)"
        assert nb.cells[2]["source"] == "print(2)"

    def test_insert_without_cell_type_returns_error(self, sandbox_dir):
        file_path = "nb.ipynb"
        _write_notebook(sandbox_dir, file_path, [("code", "print(1)")])

        result = notebook_edit_main(
            notebook_path=file_path, new_source="new cell", edit_mode="insert"
        )

        assert result.startswith("Error:")
        assert "cell_type" in result

    def test_replace_without_cell_id_returns_error(self, sandbox_dir):
        file_path = "nb.ipynb"
        _write_notebook(sandbox_dir, file_path, [("code", "print(1)")])

        result = notebook_edit_main(notebook_path=file_path, new_source="print(2)")

        assert result.startswith("Error:")
        assert "cell_id" in result

    def test_missing_notebook_returns_error(self, sandbox_dir):
        result = notebook_edit_main(
            notebook_path="missing.ipynb", new_source="x", cell_id="anything"
        )

        assert result.startswith("Error:")
        assert "does not exist" in result

    def test_path_escape_returns_permission_error_no_exception(self, sandbox_dir):
        result = notebook_edit_main(
            notebook_path="../../etc/passwd", new_source="x", cell_id="anything"
        )

        assert result.startswith("Error:")
        assert "outside the allowed directory" in result
