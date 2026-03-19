import os
from typing import List


def main(directory: str) -> str:
    """
    List all files in a directory recursively.

    Args:
        directory (str): Path to the directory.

    Returns:
        str: Formatted list of file paths.
    """
    if not directory or not os.path.exists(directory):
        return f"Directory '{directory}' does not exist."

    # Normalize directory path
    directory = os.path.abspath(directory)

    files_list: List[str] = [
        os.path.join(root, filename).replace(directory, '').lstrip(os.path.sep)
        for root, dirs, files in os.walk(directory)
        for filename in files
    ]

    if not files_list:
        return f"No files found in directory '{directory}'."

    files_formatted = "\n- ".join(files_list)
    return f"File paths in '{directory}':\n- {files_formatted}"