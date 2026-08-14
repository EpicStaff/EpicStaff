# Notebook Edit Tool
import os
from pathlib import Path
from typing import List, Optional

VALID_EDIT_MODES = ("replace", "insert", "delete")
VALID_CELL_TYPES = ("code", "markdown")


class RouteTool:
    @staticmethod
    def _is_path_within_path(source_path: Path, dest_path: Path) -> bool:
        source_path = source_path.resolve()
        dest_path = dest_path.resolve()
        return dest_path in source_path.parents or source_path == dest_path

    @staticmethod
    def is_path_has_permission(path: Path | str) -> bool:
        save_file_path = os.getenv("CONTAINER_SAVEFILES_PATH", ".")
        return RouteTool._is_path_within_path(path, Path(save_file_path))

    def construct_savepath(self, *, frompath: Path | str) -> Path:
        save_file_path = os.getenv("CONTAINER_SAVEFILES_PATH", ".")
        return Path(save_file_path) / Path(frompath)


def _find_cell_index(cells, cell_id: str) -> Optional[int]:
    for idx, cell in enumerate(cells):
        if cell.get("id") == cell_id:
            return idx
    return None


def _missing_cell_error(cells, notebook_path: str, cell_id: str) -> str:
    available: List[str] = [str(cell.get("id")) for cell in cells[:10]]
    available_str = ", ".join(available) if available else "(notebook has no cells)"
    return (
        f"Error: cell_id '{cell_id}' not found in {notebook_path}. "
        f"Available cell ids (first 10): {available_str}"
    )


def main(
    notebook_path: str,
    new_source: str,
    cell_id: str | None = None,
    cell_type: str | None = None,
    edit_mode: str = "replace",
) -> str:
    """
    Replace, insert, or delete a cell in a Jupyter notebook. Never raises:
    all failures are returned as readable error strings.
    """
    try:
        import nbformat
        from nbformat.v4 import new_code_cell, new_markdown_cell

        if not notebook_path:
            return "Error: notebook_path argument is mandatory and was not given to the tool."

        if new_source is None:
            return "Error: new_source argument is mandatory and was not given to the tool."

        edit_mode = edit_mode or "replace"

        if edit_mode not in VALID_EDIT_MODES:
            return (
                f"Error: edit_mode must be one of {VALID_EDIT_MODES}, got '{edit_mode}'."
            )

        if edit_mode in ("replace", "delete") and not cell_id:
            return f"Error: cell_id is required for edit_mode='{edit_mode}'."

        if edit_mode == "insert" and not cell_type:
            return "Error: cell_type is required for edit_mode='insert'."

        if cell_type is not None and cell_type not in VALID_CELL_TYPES:
            return f"Error: cell_type must be one of {VALID_CELL_TYPES}, got '{cell_type}'."

        route_tool = RouteTool()
        notebook_savepath = route_tool.construct_savepath(frompath=notebook_path)

        if not RouteTool.is_path_has_permission(notebook_savepath):
            return f"Error: path {notebook_path} is outside the allowed directory."

        if not notebook_savepath.exists():
            return f"Error: notebook {notebook_path} does not exist."

        if notebook_savepath.is_dir():
            return f"Error: {notebook_path} is a directory, not a file."

        try:
            nb = nbformat.read(str(notebook_savepath), as_version=4)
        except Exception as e:
            return f"Error: could not parse notebook {notebook_path}: {e}"

        if edit_mode in ("replace", "delete"):
            index = _find_cell_index(nb.cells, cell_id)
            if index is None:
                return _missing_cell_error(nb.cells, notebook_path, cell_id)

            if edit_mode == "delete":
                del nb.cells[index]
            else:
                cell = nb.cells[index]
                cell["source"] = new_source
                cell["outputs"] = []
                cell["execution_count"] = None
        else:  # insert
            new_cell = (
                new_code_cell(source=new_source)
                if cell_type == "code"
                else new_markdown_cell(source=new_source)
            )

            if cell_id is None:
                nb.cells.insert(0, new_cell)
            else:
                index = _find_cell_index(nb.cells, cell_id)
                if index is None:
                    return _missing_cell_error(nb.cells, notebook_path, cell_id)
                nb.cells.insert(index + 1, new_cell)

            cell_id = new_cell.get("id")

        try:
            nbformat.write(nb, str(notebook_savepath))
        except Exception as e:
            return f"Error: could not write notebook {notebook_path}: {e}"

        return f"{edit_mode} cell {cell_id} in {notebook_path}"
    except Exception as e:
        return f"Error: failed to edit notebook. Unexpected exception: {e}"
