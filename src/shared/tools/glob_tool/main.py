# Glob Tool
import os
from pathlib import Path
from typing import List, Tuple

MAX_RESULTS = 100


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


def _collect_files_with_mtime(
    matches: List[Path],
) -> List[Tuple[Path, float]]:
    files: List[Tuple[Path, float]] = []
    for match in matches:
        try:
            if not match.is_file():
                continue
            mtime = match.stat().st_mtime
        except OSError:
            continue
        files.append((match, mtime))
    return files


def main(pattern: str, path: str | None = None) -> str:
    """
    Find files by glob pattern, sorted newest-first. Never raises: all
    failures are returned as readable error strings.
    """
    try:
        if not pattern:
            return "Error: pattern argument is mandatory and was not given to the tool."

        path = path or "."

        route_tool = RouteTool()
        search_root = route_tool.construct_savepath(frompath=path)

        if not RouteTool.is_path_has_permission(search_root):
            return f"Error: path {path} is outside the allowed directory."

        if not search_root.exists():
            return f"Error: path {path} does not exist."

        if not search_root.is_dir():
            return f"Error: path {path} is not a directory."

        try:
            matches = list(search_root.glob(pattern))
            matches = [m for m in matches if RouteTool.is_path_has_permission(m)]
        except (ValueError, NotImplementedError) as e:
            return f"Error: invalid glob pattern '{pattern}': {e}"

        files = _collect_files_with_mtime(matches)

        if not files:
            return f"No files match pattern {pattern}"

        files.sort(key=lambda item: item[1], reverse=True)

        total = len(files)
        capped = files[:MAX_RESULTS]

        rendered = []
        for file_path, _mtime in capped:
            try:
                rel = file_path.relative_to(search_root)
            except ValueError:
                rel = file_path
            rendered.append(str(rel))

        result = "\n".join(rendered)

        if total > MAX_RESULTS:
            result += (
                f"\n(showing {MAX_RESULTS} of {total} matches — narrow the pattern)"
            )

        return result
    except Exception as e:
        return f"Error: failed to search for files. Unexpected exception: {e}"
