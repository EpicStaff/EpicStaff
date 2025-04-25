import logging
from typing import Optional, Type, Any

logger = logging.getLogger(__name__)

from pydantic.v1 import BaseModel, Field
from crewai_tools import BaseTool


class FixedFileToolSchema(BaseModel):
    """Input for FileTool."""

    pass


class CreateFileSchema(FixedFileToolSchema):
    """Input for CreateFileTool."""

    file_path: str = Field(..., description="The path to the file.")


class CreateFileTool(BaseTool):
    name: str = "Create a file"
    description: str = "A tool that's used to Create a file."
    args_schema: Type[BaseModel] = CreateFileSchema
    file_path: Optional[str] = None

    def __init__(self, file_path: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)

        if file_path is not None:
            self.file_path = file_path
            self.description = f"A tool that's used to create a file at {file_path}."
            self.args_schema = FixedFileToolSchema
            self._generate_description()

    def _run(
        self,
        **kwargs: Any,
    ) -> Any:
        try:
            file_path = kwargs.get("file_path", self.file_path)
            with open(file_path, "x") as file:
                return "File created successfully."
        except FileExistsError:
            return "File already exists."
