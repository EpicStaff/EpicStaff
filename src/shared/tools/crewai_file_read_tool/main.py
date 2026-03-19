from typing import Optional

def main(file_path: Optional[str] = None, start_line: Optional[int] = 1, line_count: Optional[int] = None) -> str:
    """
    Read content from a file.

    Args:
        file_path (Optional[str]): Full path to the file to read.
        start_line (Optional[int]): Line number to start reading from (1-indexed, default 1).
        line_count (Optional[int]): Number of lines to read. If None, reads the entire file.

    Returns:
        str: The content of the file or an error message.
    """
    if file_path is None:
        return "Error: No file path provided."

    start_line = start_line or 1

    try:
        with open(file_path, "r") as file:
            if start_line == 1 and line_count is None:
                return file.read()

            start_idx = max(start_line - 1, 0)
            selected_lines = [
                line
                for i, line in enumerate(file)
                if i >= start_idx and (line_count is None or i < start_idx + line_count)
            ]

            if not selected_lines and start_idx > 0:
                return f"Error: Start line {start_line} exceeds the number of lines in the file."

            return "".join(selected_lines)

    except FileNotFoundError:
        return f"Error: File not found at path: {file_path}"
    except PermissionError:
        return f"Error: Permission denied when trying to read file: {file_path}"
    except Exception as e:
        return f"Error: Failed to read file {file_path}. {str(e)}"