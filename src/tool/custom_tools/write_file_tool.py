from typing import Any, Type

from loguru import logger
from pydantic import BaseModel, Field

from .route_tool import RouteTool

MAX_CONTENT_BYTES = 1024 * 1024


class WriteFileToolSchema(BaseModel):
    """Input for WriteFileTool."""

    file_path: str = Field(
        ..., description="Path to the file to write, relative to the sandbox root."
    )
    content: str = Field(..., description="Full content to write to the file.")
    overwrite: bool = Field(
        False,
        description="Must be true to overwrite an existing file. Default false.",
    )


class WriteFileTool(RouteTool):
    name: str = "Write a file's content"
    description: str = ""
    args_schema: Type[BaseModel] = WriteFileToolSchema

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._generate_description()

    def _run(self, **kwargs: Any) -> str:
        try:
            return self._run_impl(**kwargs)
        except Exception as e:
            logger.error("WriteFileTool failed unexpectedly: {}", e)
            return f"Error: failed to write file. Unexpected exception: {e}"

    def _run_impl(self, **kwargs: Any) -> str:
        file_path = kwargs.get("file_path")
        if not file_path:
            return "Error: file_path argument is mandatory and was not given to the tool."

        content = kwargs.get("content")
        if content is None:
            return "Error: content argument is mandatory and was not given to the tool."

        overwrite = bool(kwargs.get("overwrite", False))

        content_bytes = content.encode("utf-8")
        if len(content_bytes) > MAX_CONTENT_BYTES:
            return (
                f"Error: content is {len(content_bytes)} bytes, which exceeds the "
                f"{MAX_CONTENT_BYTES} byte cap. Split the write into smaller chunks."
            )

        file_savepath = self.construct_savepath(frompath=file_path)

        if not self.is_path_has_permission(file_savepath):
            return f"Error: path {file_path} is outside the allowed directory."

        if file_savepath.exists() and file_savepath.is_dir():
            return f"Error: {file_path} is a directory. Choose a file path instead."

        if file_savepath.exists() and not overwrite:
            return (
                f"Error: file {file_path} already exists. Pass overwrite=true to replace it."
            )

        try:
            file_savepath.parent.mkdir(parents=True, exist_ok=True)
            file_savepath.write_bytes(content_bytes)
        except Exception as e:
            return f"Error: could not write file {file_path}: {e}"

        return f"File written: {file_path} ({len(content_bytes)} bytes)"
