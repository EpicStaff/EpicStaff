# Write File Tool
import os
from pathlib import Path

MAX_CONTENT_BYTES = 1024 * 1024


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


def main(file_path: str, content: str, overwrite: bool = False) -> str:
    """
    Create a new file or overwrite an existing one, with an explicit
    overwrite guard. Never raises: all failures are returned as readable
    error strings.
    """
    try:
        if not file_path:
            return (
                "Error: file_path argument is mandatory and was not given to the tool."
            )

        if content is None:
            return "Error: content argument is mandatory and was not given to the tool."

        overwrite = bool(overwrite)

        content_bytes = content.encode("utf-8")
        if len(content_bytes) > MAX_CONTENT_BYTES:
            return (
                f"Error: content is {len(content_bytes)} bytes, which exceeds the "
                f"{MAX_CONTENT_BYTES} byte cap. Split the write into smaller chunks."
            )

        route_tool = RouteTool()
        file_savepath = route_tool.construct_savepath(frompath=file_path)

        if not RouteTool.is_path_has_permission(file_savepath):
            return f"Error: path {file_path} is outside the allowed directory."

        if file_savepath.exists() and file_savepath.is_dir():
            return f"Error: {file_path} is a directory. Choose a file path instead."

        if file_savepath.exists() and not overwrite:
            return f"Error: file {file_path} already exists. Pass overwrite=true to replace it."

        file_savepath.parent.mkdir(parents=True, exist_ok=True)
        file_savepath.write_bytes(content_bytes)

        return f"File written: {file_path} ({len(content_bytes)} bytes)"
    except Exception as e:
        return f"Error: failed to write file. Unexpected exception: {e}"
