# CreateFileTool

from pathlib import Path
import os


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


def main(file_path: str):
    try:
        full_path = RouteTool().construct_savepath(frompath=file_path)
        if not RouteTool.is_path_has_permission(full_path):
            return f"Error: path {file_path} is outside the allowed directory."
        os.makedirs(full_path.parent, exist_ok=True)
        with open(full_path, "x"):
            pass
        return f"File created successfully in {file_path}"
    except FileExistsError:
        return f"File {file_path} already exists, no need to create it"
    except PermissionError:
        return "Given filepath doesn't have access to the specified directory."
    except Exception as e:
        return f"Didn't manage to create a file. Unexpected exception occurred: {e}"
