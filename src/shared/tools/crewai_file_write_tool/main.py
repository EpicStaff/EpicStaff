import os
from typing import Any


def strtobool(val) -> bool:
    if isinstance(val, bool):
        return val
    val = str(val).lower()
    if val in ("y", "yes", "t", "true", "on", "1"):
        return True
    elif val in ("n", "no", "f", "false", "off", "0"):
        return False
    else:
        raise ValueError(f"invalid value to cast to bool: {val!r}")


def main(filename: str, content: str, directory: str = "./", overwrite: Any = False) -> str:
    """
    Write content to a specified file. Creates directory if it doesn't exist.
    
    Args:
        filename (str): Name of the file.
        content (str): Content to write.
        directory (str, optional): Directory path. Defaults to "./".
        overwrite (str | bool, optional): Overwrite existing file. Defaults to False.

    Returns:
        str: Success or error message.
    """
    try:
        # Create directory if needed
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

        # Full file path
        filepath = os.path.join(directory, filename)

        # Convert overwrite to boolean
        overwrite = strtobool(overwrite)

        # Prevent overwriting if not allowed
        if os.path.exists(filepath) and not overwrite:
            return f"File {filepath} already exists and overwrite option was not passed."

        # Write content
        mode = "w" if overwrite else "x"
        with open(filepath, mode, encoding="utf-8") as f:
            f.write(content)

        return f"Content successfully written to {filepath}"
    except FileExistsError:
        return f"File {filepath} already exists and overwrite option was not passed."
    except Exception as e:
        return f"An error occurred: {str(e)}"