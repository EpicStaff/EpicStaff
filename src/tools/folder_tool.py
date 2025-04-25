import logging
logger = logging.getLogger(__name__)
logger.debug(f"Entered {__file__}")
from pydantic.v1 import BaseModel, Field
from crewai_tools import BaseTool
from typing import Type, Any
import os
from datetime import datetime
from langchain.tools import tool




class FolderToolSchema(BaseModel):
    """
    Input schema for FolderTool, specifying the required parameters for listing files in a folder.
    """
    folder_path: str = Field(..., description="folder path to list files from.")
    recursive: bool = Field(False, description="whether to list files recursively. Default is False.")

class FolderTool(BaseTool):
    """
    Tool to create and execute code using Open Interpreter.
    """
    name: str = "FolderTool"
    description: str = "Tool to list files in a specified folder, with the option to list recursively. Takes in two parameters: 'folder_path' - the path to the folder, and 'recursive' - whether to list files recursively."
    args_schema: Type[BaseModel] = FolderToolSchema

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._generate_description()  # Call to the inherited method to set the initial description

    def _run(self, **kwargs: Any) -> Any:
        """
        Lists all files in a specified folder, with the option to list recursively.

        Parameters:
        - folder_path: Path to the folder.
        - recursive: Whether to list files recursively.

        Returns:
        A string indicating the number of files listed and the first 5 files, 
        with a note on where to find the rest in the output file.
        """
        folder_path = kwargs.get('folder_path')
        recursive = kwargs.get('recursive')
        # Generate the output file name with a timestamp
        output_file_name = f"find_{datetime.now().strftime('%Y%m%d%H%M%S')}.txt"
        # Assuming the output is to be saved in the current directory, modify as needed
        output_file_path = os.path.join(os.getcwd(), output_file_name)
        files_listed = []

        # List files in the specified folder recursively or not, based on the recursive parameter
        if recursive:
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    files_listed.append(os.path.join(root, file))
        else:
            for item in os.listdir(folder_path):
                if os.path.isfile(os.path.join(folder_path, item)):
                    files_listed.append(os.path.join(folder_path, item))

        # Write the list of files to the output file
        with open(output_file_path, 'w') as output_file:
            for file_path in files_listed:
                output_file.write(file_path + '\n')

        # Prepare the output message
        if len(files_listed) > 5:
            first_5_files = "\n".join(files_listed[:5])
            message = (f"{len(files_listed)} files were listed. Here are the first 5 lines:\n\n{first_5_files}\n" 
                f"\n-- TOOL MESSAGE: End of part! --\n"
                f"The current output segment has concluded. Note: Additional content not displayed here.\n"
                f"ACTION REQUIRED: To continue reading the remaining lines, open the file: '{output_file_path}'\n")
        else:
            files = "\n".join(files_listed)
            message = f"{len(files_listed)} files were listed. Here are the files:\n{files}"

        return message
    