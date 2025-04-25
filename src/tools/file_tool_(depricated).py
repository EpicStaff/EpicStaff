import logging
logger = logging.getLogger(__name__)
logger.debug(f"Entered {__file__}")
from langchain.tools import tool
from typing import Optional, Type, Any
from pydantic.v1 import BaseModel, Field, validator
from crewai_tools import BaseTool
from enum import Enum

#import traceback
#import sys

    


class FixedFileToolSchema(BaseModel):
    """Input for FileTool."""
    pass

class FileToolSchema(FixedFileToolSchema):
    """Input for FileTool."""
    file_path: str = Field(..., description="The path to the file.")
    operation: str = Field(..., description="The operation to perform on the file.")
    line_number: int = Field(None, description="The line number to start reading from. Line numbers are 1-based.")
    num_lines: Optional[int] = Field(None, description="The number of lines to read starting from line_number.")
    expected_text: str = Field(None, description="The text expected to be on the specified line for editing.")
    new_text: str = Field(None, description="The new text to replace the existing text on the specified line.")
    append_text: str = Field(None, description="The text to be appended to the file.")

    @validator('file_path')
    def check_file_exists(cls, v, values):
        import os
        if values['operation'] != "create" and not os.path.exists(v):
            raise ValueError("file must exist for the specified operation")
        return v

class FileTool(BaseTool):
    name: str = "General purpose file management tool"
    description: str = "Manage 'append', 'edit', 'create', 'count_lines', 'read', 'create' file operations"
    args_schema: Type[BaseModel] = FileToolSchema
    file_path: Optional[str] = None
    
    def __init__(self, file_path: Optional[str] = None, **kwargs):
        # print("Entering FileTool constructor...")
        # print(f"file_path: {file_path}")
        # print(f"kwargs: {kwargs}")
        super().__init__(**kwargs)
        self.description = """
    Supported Operations:
    - 'append': Adds specified text to the end of the file.
      Parameters:
        - file_path: Path to the file.
        - append_text: Text to be appended.

    - 'edit': Modifies a specific line in the file, provided the existing content matches the expected input.
      Parameters:
        - file_path: Path to the file.
        - line_number: Line number to edit.
        - expected_text: The text currently expected on the line.
        - new_text: The new text to replace the existing line content.

    - 'create': Generates a new file or gives an error if the file already exists.
      Parameters:
        - file_path: Path to the file where the new file will be created.
        - append_text: Text to be appended. 

    - 'count_lines': Calculates the total number of lines in the file.
      Parameters:
        - file_path: Path to the file.

    - 'get_line': Retrieves the content of a specific line based on line number.
      Parameters:
        - file_path: Path to the file.
        - line_number: The line number whose content is to be retrieved.

    - 'read': Extracts a segment of the file starting from a specified line and covering a defined number of subsequent lines.
      Parameters:
        - file_path: Path to the file.
        - line_number: The starting line number from where to begin reading.
        - num_lines: The number of lines to read from the starting line. If not specified, reads all lines starting from `line_number`.
    Line numbers are 1-based, meaning the first line is line 1.
    """
        if file_path is not None:
            self.file_path = file_path
        else:
            self._generate_description()
    
    def _run(self, **kwargs: Any) -> Any:
        #self.args_schema = FixedFileToolSchema *args:Any
        try:
            operation = kwargs.get('operation')
            #print(f"Operation: {operation}, Type:{type(operation)}") #Debug
            #for each in kwargs print th key and value and type
            # print("Printing kwargs...")
            # for key, value in kwargs.items():
            #     print(f"{key}: {value}, Type: {type(value)}") #Debug
            # print("Printing args...")
            # for each in args:
            #     print(f"{each}")
            #traceback.print_stack(file=sys.stdout)
            #print args
            #print(f"args: {args}") #Debug
            #print(f"kwargs: {kwargs}") #Debug
            if operation == 'append':
                return self.__append_text(**kwargs)
            elif operation == 'edit':
                return self.__edit_line(**kwargs)
            elif operation == 'create':
                return self.__create_file(**kwargs)
            elif operation == 'count_lines':
                return self.__count_lines(**kwargs)
            elif operation == 'get_line':
                return self.__get_line(**kwargs)
            elif operation == 'read':
                return self.__read_file(**kwargs)
            else:
                self.description = f"I made an invalid operation '{operation}'. Valid operations are: append, edit, create, count_lines, get_line, read."
                #traceback.print_stack(file=sys.stderr)
                self._generate_description()
                return self.description
        except Exception as e:
            error_message = f"Error processing operation '{kwargs.get('operation', 'unknown')}'. Exception type: {type(e).__name__}, Exception info: {e}, Object state: {self.__dict__}"
            return error_message
        	
        
    def __append_text(self, file_path, append_text=None, **kwargs):
        # print(f"file_path: {file_path}")
        # print(f"append_text: {append_text}")
        # print(f"kwargs: {kwargs}")
        try:
            with open(file_path, 'a') as file:
                file.write(append_text + '\n')
            return "Text appended successfully."
        except Exception as e:
            return f"Failed to append text: {e}"

    def __edit_line(self, file_path, line_number, expected_text, new_text, **kwargs):
        """Edits a specific line in the file if the expected text matches."""
        lines = self.__read_file_lines(file_path)
        if not 1 <= line_number <= len(lines):
            return f"I made an error: Line number {line_number} is out of the file's range. The file has {len(lines)} lines. The first line is line 1."
        # Check if the expected text matches the current line content
        current_line = lines[line_number - 1].rstrip("\n")
        if expected_text is not None and current_line != expected_text:
            return f"I made an Error: Expected text does not match the text on line {line_number}."
        # Replace the line with new text
        lines[line_number - 1] = new_text + '\n'
        # Write the updated lines back to the file directly within this method
        with open(file_path, 'w') as file:
            file.writelines(lines)
        return "Line edited successfully."

    def __read_file(self, file_path, line_number=1, num_lines=None, **kwargs):
        """
        Reads a specific number of lines starting from a given line number from the file at file_path.
        Parameters:
            file_path: The path to the file to read.
            line_number (optional): The line number from which to start reading. Defaults to 1.
            num_lines (optional): The number of lines to read starting from line_number. If None, reads to the end of the file.
        Returns:
            line numbers and their contents if successful.
            Error message if an input constraint is violated or an error occurs.
        """
        # Normalize num_lines to handle 0 as 'read all lines' and enforce positive integers
        if num_lines is not None:
            if num_lines == 0:
                num_lines = None  # Normalize zero to None to indicate "read all lines"
            elif num_lines < 1:
                return "I made a mistake, I forgot that number of lines has to be positive."
        
        # Ensure line_number starts at least from 1
        if line_number < 1:
            return "I made a mistake, I forgot that the first line is 1."
        
        lines = self.__read_file_lines(file_path)
        
        
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

    def __create_file(self, file_path, **kwargs):
        """Creates a new file or overwrites an existing one."""
        # print(f"__create file_path: {file_path}")
        # print(f"kwargs: {kwargs}")  
        # print(f"{kwargs}")
        try:
            with open(file_path, 'x') as file:
                return "File created successfully."
        except FileExistsError:
            return "File already exists."

    def __count_lines(self, file_path, **kwargs):
        """Counts the number of lines in the specified file."""
        lines = self.__read_file_lines(file_path)
        return f"Total lines: {len(lines)}"

    def __get_line(self, file_path, line_number, **kwargs):
        """Retrieves and returns a specific line from the specified file."""
        lines = self.__read_file_lines(file_path)
        if line_number < 1 or line_number > len(lines):
            return "Line number is out of range."
        return lines[line_number - 1].strip()

    def __read_file_lines(self, file_path):
        """Reads all lines from the specified file and returns them as a list."""
        with open(file_path, 'r') as file:
            return file.readlines()