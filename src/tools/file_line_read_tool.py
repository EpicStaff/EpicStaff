import os
import logging
logger = logging.getLogger(__name__)
from langchain.tools import tool
from typing import Optional, Type, Any
from pydantic.v1 import BaseModel, Field, validator
from crewai_tools import BaseTool


class FixedFileToolSchema(BaseModel):
    """Input for LineReadFileTool"""
    

class LineReadFileToolSchema(FixedFileToolSchema):
    """Input for LineReadFileTool"""
    file_path: str = Field(..., description="Mandatory file full path to read the file")
    line_number: int = Field(..., description="Manadatory line number (1-based) to start reading from.")
    num_lines: Optional[int] = Field(..., description="Optional number of lines to read from the starting line. If not specified, reads all lines starting from `line_number`.")

class LineReadFileTool(BaseTool):
    name: str = "Read a file's content by line number"
    description: str = "A tool that can be used to read a file's content by line number."
    args_schema: Type[BaseModel] = LineReadFileToolSchema
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    num_lines: Optional[int] = None
    
    def __init__(self, file_path: Optional[str] = None, line_number: Optional[int] = None, num_lines: Optional[int] = None, **kwargs):
        super().__init__(**kwargs)
        if file_path is not None  and line_number is not None:
            self.file_path = file_path
            self.line_number = line_number
            self.num_lines = num_lines
            self.description = f"A tool that can be used to read {file_path}'s content by line number."
            self.args_schema = FixedFileToolSchema
            self._generate_description()
    
    def _run(
        self,
        **kwargs: Any,
    ) -> Any:
        file_path = kwargs.get('file_path', self.file_path)
        line_number = kwargs.get('line_number', self.line_number)
        num_lines = kwargs.get('num_lines', self.num_lines)
        if num_lines is not None:
            if num_lines == 0:
                num_lines = None  # Normalize zero to None to indicate "read all lines"
            elif num_lines < 1:
                return "I made a mistake, I forgot that number of lines has to be positive."
        # Ensure line_number starts at least from 1
        if line_number < 1:
            return "I made a mistake, I forgot that the first line is 1."
        
        with open(file_path, 'r') as file:
            lines = file.readlines()
        
        # Validate line_number to ensure it's within the range of the file's line count.
        if line_number > len(lines):
            return f"I made a mistake: Line number {line_number} is out of the file's range."

        # Calculate the end index for slicing lines; handle case where num_lines is None
        end_index = (line_number - 1) + num_lines if num_lines else len(lines) 
        selected_lines = lines[line_number - 1:end_index]  # Adjust for zero-based index

        if not selected_lines:
            return "No lines found starting from the specified line number."

        # Format output to include line numbers with their respective contents
        content = ''.join([f"{idx + line_number}: {line}" for idx, line in enumerate(selected_lines)])
        return content
        