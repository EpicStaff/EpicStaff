import os
import logging

logger = logging.getLogger(__name__)
logger.debug(f"Entered {__file__}")
from langchain.tools import tool
from typing import Optional, Type, Any
from pydantic.v1 import BaseModel, Field, validator
from crewai_tools import BaseTool


class FixedFileToolSchema(BaseModel):
    """Input for FileCountLinesTool."""


class FileCountLinesToolSchema(FixedFileToolSchema):
    """Input for FileCountLinesTool"""

    file_path: str = Field(..., description="The path to the file.")


class FileCountLinesTool(BaseTool):
    name: str = "Count a file's lines"
    description: str = "A tool that can be used to count the number of lines in a file."
    args_schema: Type[BaseModel] = FileCountLinesToolSchema
    file_path: Optional[str] = None

    def __init__(self, file_path: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        if file_path is not None:
            self.file_path = file_path
            self.description = (
                f"A tool that can be used to count the number of lines in {file_path}."
            )
            self.args_schema = FixedFileToolSchema
            self._generate_description()

    def _run(
        self,
        **kwargs: Any,
    ) -> Any:
        file_path = kwargs.get("file_path", self.file_path)
        try:
            with open(file_path, "r") as file:
                lines = file.readlines()
                return f"Total lines: {len(lines)}"
        except Exception as e:
            return f"Error reading file: {e}"
