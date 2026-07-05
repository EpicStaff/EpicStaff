from typing import Any, List, Optional, Type

from loguru import logger
from pydantic import BaseModel, Field

from .route_tool import RouteTool

VALID_EDIT_MODES = ("replace", "insert", "delete")
VALID_CELL_TYPES = ("code", "markdown")


class NotebookEditToolSchema(BaseModel):
    """Input for NotebookEditTool."""

    notebook_path: str = Field(
        ..., description="Path to the .ipynb file, relative to the sandbox root."
    )
    new_source: str = Field(
        ..., description="New cell content. Ignored when edit_mode is 'delete'."
    )
    cell_id: str | None = Field(
        None,
        description=(
            "Target cell id. Required for replace/delete. For insert, the new cell "
            "is inserted after this cell id; omit to insert at the top."
        ),
    )
    cell_type: str | None = Field(
        None,
        description="'code' or 'markdown'. Required for insert; ignored otherwise.",
    )
    edit_mode: str = Field(
        "replace", description="'replace', 'insert', or 'delete'. Default 'replace'."
    )


class NotebookEditTool(RouteTool):
    name: str = "Replace, insert, or delete a Jupyter notebook cell"
    description: str = ""
    args_schema: Type[BaseModel] = NotebookEditToolSchema

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._generate_description()

    def _run(self, **kwargs: Any) -> str:
        try:
            return self._run_impl(**kwargs)
        except Exception as e:
            logger.error("NotebookEditTool failed unexpectedly: {}", e)
            return f"Error: failed to edit notebook. Unexpected exception: {e}"

    def _run_impl(self, **kwargs: Any) -> str:
        import nbformat
        from nbformat.v4 import new_code_cell, new_markdown_cell

        notebook_path = kwargs.get("notebook_path")
        if not notebook_path:
            return "Error: notebook_path argument is mandatory and was not given to the tool."

        new_source = kwargs.get("new_source")
        if new_source is None:
            return "Error: new_source argument is mandatory and was not given to the tool."

        cell_id = kwargs.get("cell_id")
        cell_type = kwargs.get("cell_type")
        edit_mode = kwargs.get("edit_mode") or "replace"

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

        notebook_savepath = self.construct_savepath(frompath=notebook_path)
        if not self.is_path_has_permission(notebook_savepath):
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
            index = self._find_cell_index(nb.cells, cell_id)
            if index is None:
                return self._missing_cell_error(nb.cells, notebook_path, cell_id)

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
                index = self._find_cell_index(nb.cells, cell_id)
                if index is None:
                    return self._missing_cell_error(nb.cells, notebook_path, cell_id)
                nb.cells.insert(index + 1, new_cell)

            cell_id = new_cell.get("id")

        try:
            nbformat.write(nb, str(notebook_savepath))
        except Exception as e:
            return f"Error: could not write notebook {notebook_path}: {e}"

        return f"{edit_mode} cell {cell_id} in {notebook_path}"

    @staticmethod
    def _find_cell_index(cells, cell_id: str) -> Optional[int]:
        for idx, cell in enumerate(cells):
            if cell.get("id") == cell_id:
                return idx
        return None

    @staticmethod
    def _missing_cell_error(cells, notebook_path: str, cell_id: str) -> str:
        available: List[str] = [str(cell.get("id")) for cell in cells[:10]]
        available_str = ", ".join(available) if available else "(notebook has no cells)"
        return (
            f"Error: cell_id '{cell_id}' not found in {notebook_path}. "
            f"Available cell ids (first 10): {available_str}"
        )
