import os
import logging
from typing import Optional, Type, Any

logger = logging.getLogger(__name__)
logger.debug(f"Entered {__file__}")

from pydantic.v1 import BaseModel, Field, validator
from crewai_tools import BaseTool


class FixedFileToolSchema(BaseModel):
    """Input for AppendFileTool."""


class AppendFileToolSchema(FixedFileToolSchema):
    """Input for appending text to a file."""

    file_path: str = Field(
        ..., description="Manadatory file full path to append the text."
    )
    append_text: str = Field(
        ..., description="Mandatory text to be appended to the file."
    )


class AppendFileTool(BaseTool):
    name: str = "Append text to a file"
    description: str = "A tool that can be used to append text to a file."
    args_schema: Type[BaseModel] = AppendFileToolSchema
    file_path: Optional[str] = None
    append_text: Optional[str] = None

    def __init__(
        self,
        file_path: Optional[str] = None,
        append_text: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)

        if file_path is not None:
            self.file_path = file_path
            self.append_text = append_text
            self.description = f"A tool that can be used to append text to {file_path}."
            self.args_schema = FixedFileToolSchema
            self._generate_description()

    def _run(
        self,
        **kwargs: Any,
    ) -> Any:
        try:
            file_path = kwargs.get("file_path", self.file_path)
            append_text = kwargs.get("append_text", self.append_text)
            with open(file_path, "a") as file:
                file.write(append_text + "\n")
            return "Text appended successfully."
        except Exception as e:
            return f"Failed to append text: {e}"
