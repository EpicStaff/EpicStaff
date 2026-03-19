# Standalone DirectorySearchTool with main()
import os
import string
from typing import Optional, Type

from pydantic import BaseModel, Field


class FixedDirectorySearchToolSchema(BaseModel):
    """Input for DirectorySearchTool."""
    search_query: str = Field(
        ...,
        description="Mandatory search query you want to use to search the directory's content",
    )


class DirectorySearchToolSchema(FixedDirectorySearchToolSchema):
    """Input for DirectorySearchTool."""
    directory: str = Field(..., description="Mandatory directory you want to search")


class DirectorySearchTool:
    """Tool to search files in a directory by content."""

    name: str = "Search a directory's content"
    description: str = (
        "A tool that can be used to search a query from a directory's content."
    )
    args_schema: Type[BaseModel] = DirectorySearchToolSchema

    def __init__(self, directory: Optional[str] = None):
        self.directories = []
        if directory:
            self.add(directory)
            self.description = f"A tool that can be used to search a query from the {directory} directory's content."
            self.args_schema = FixedDirectorySearchToolSchema

    def add(self, directory: str) -> None:
        """Add a directory to search."""
        if os.path.isdir(directory):
            self.directories.append(directory)
        else:
            raise ValueError(f"Directory does not exist: {directory}")

    def _run(
        self,
        search_query: str,
        directory: Optional[str] = None,
        limit: int = 5,
    ) -> str:
        """
        Search the directories for files containing the query.
        Exact or partial word match, normalized and punctuation removed.
        """
        if directory:
            self.add(directory)

        results = []
        query = search_query.lower()

        for dir_path in self.directories:
            for root, _, files in os.walk(dir_path):
                for file_name in files:
                    file_path = os.path.join(root, file_name)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read().lower()

                        # Remove punctuation and split into words
                        translator = str.maketrans("", "", string.punctuation)
                        words = content.translate(translator).split()

                        # Match words containing the query
                        matches = [w for w in words if query in w]

                        if matches:
                            matches = matches[:limit]  # limit number of matches
                            results.append(f"File: {file_path}\nMatches: {', '.join(matches)}\n")
                    except Exception as e:
                        results.append(f"File: {file_path}\nError reading file: {e}\n")

        if not results:
            return "No matches found."
        return "\n".join(results)


def main(search_query: str, directory: Optional[str] = None, limit: int = 5) -> str:
    """
    Entry point for the DirectorySearchTool.

    Args:
        search_query (str): Query to search for.
        directory (Optional[str]): Directory to search. Can be None if directories were pre-added.
        limit (int): Maximum number of matches per file.

    Returns:
        str: Search results.
    """
    tool = DirectorySearchTool(directory=directory)
    return tool._run(
        search_query=search_query,
        limit=limit,
    )