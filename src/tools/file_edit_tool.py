import os
import logging
logger = logging.getLogger(__name__)
from langchain.tools import tool
from typing import Optional, Type, Any
from pydantic.v1 import BaseModel, Field, validator
from crewai_tools import BaseTool

    


class FixedFileToolSchema(BaseModel):
    """Input for EditFileTool."""
    

class FileEditToolSchema(FixedFileToolSchema):
    """Input for EditFileTool."""
    file_path: str = Field(..., description="Mandatory file full path to edit the file")
    line_number: int = Field(..., description="Mandatory line number (1-based) to edit.")
    expected_text: str = Field(..., description="Mandatory text to be replaced on the specified line.")
    new_text: str = Field(..., description="Manadatory new text to replace the expected text.")

class EditFileTool(BaseTool):
    name: str = "Edit a file's line"
    description: str = "A tool that can be used to edit a specific line in a file."
    args_schema: Type[BaseModel] = FileEditToolSchema
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    expected_text: Optional[str] = None
    new_text: Optional[str] = None
    
    def __init__(self, file_path: Optional[str] = None, 
                 line_number: Optional[int] = None, 
                 expected_text: Optional[str] = None, 
                 new_text: Optional[str] = None ,**kwargs):
        super().__init__(**kwargs)
        
        if file_path is not None or line_number is not None or expected_text is not None or new_text is not None:
            self.file_path = file_path
            self.line_number = line_number
            self.expected_text = expected_text
            self.new_text = new_text
            self.description = f"A tool that can be used to edit a specific line in {file_path}."
            self.args_schema = FixedFileToolSchema
            self._generate_description()
    
    def _run(
        self, 
        **kwargs: Any,
    ) -> Any:
        file_path = kwargs.get('file_path', self.file_path)
        line_number = kwargs.get('line_number', self.line_number)
        expected_text = kwargs.get('expected_text', self.expected_text)
        new_text = kwargs.get('new_text', self.new_text)
        with open(file_path, 'r') as file:
            lines =  file.readlines()
        # Check if the line number is within the file's range
        if not 1 <= line_number <= len(lines):
            return f"I made an error: Line number {line_number} is out of the file's range. The file has {len(lines)} lines. The first line is line 1."
        
        # Check if the expected text matches the current line content
        current_line = lines[line_number - 1].rstrip("\n")
        
        if expected_text is not None and current_line != expected_text:
            return f"I made an Error: Expected text does not match the text on line {line_number}."
        
        # Replace the line with new text
        lines[line_number - 1] = new_text + '\n'
        
        # Write the updated lines back to the file directly within this method
        try:
            with open(file_path, 'w') as file:
                file.writelines(lines)
        except Exception as e:
            return f"There was an eeror writing to file {file_path}: {e}"
        
        return "Line edited successfully."

    
    
        