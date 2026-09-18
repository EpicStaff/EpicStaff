# AppendFileTool

import os
from pathlib import Path


class RouteTool:
    @staticmethod
    def _is_path_within_path(source_path: Path, dest_path: Path) -> bool:
        source_path = source_path.resolve()
        dest_path = dest_path.resolve()
        return dest_path in source_path.parents or source_path == dest_path

    @staticmethod
    def is_path_has_permission(path: Path | str) -> bool:
        save_file_path = os.getenv("CONTAINER_SAVEFILES_PATH", ".")
        return RouteTool._is_path_within_path(path, Path(save_file_path))

    def construct_savepath(self, *, frompath: Path | str) -> Path:
        save_file_path = os.getenv("CONTAINER_SAVEFILES_PATH", ".")
        return Path(save_file_path) / Path(frompath)


def main(file_path: str, append_text: str):
    try:
        full_path = RouteTool().construct_savepath(frompath=file_path)
        if not RouteTool.is_path_has_permission(full_path):
            return f"Error: path {file_path} is outside the allowed directory."
        with open(full_path, "a", encoding="utf-8") as file:
            file.write(append_text + "\n")
        return f"Text appended successfully to the file {file_path}."
    except FileNotFoundError:
        return f"File {file_path} not found."
    except PermissionError:
        return "Given filepath doesn't have access to the specified directory."
    except Exception as e:
        return f"Didn't manage to append to a file. Unexpected exception occurred: {e}"
