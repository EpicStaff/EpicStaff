from pathlib import Path
from typing import Any, List, Tuple, Type

from loguru import logger
from pydantic import BaseModel, Field

from .route_tool import RouteTool

MAX_RESULTS = 100


class GlobToolSchema(BaseModel):
    """Input for GlobTool."""

    pattern: str = Field(
        ...,
        description=(
            "Glob pattern to match file paths against, e.g. '**/*.csv' or "
            "'reports/2026-*.pdf'."
        ),
    )
    path: str | None = Field(
        None,
        description=(
            "Directory to search in, relative to the sandbox root. Defaults to "
            "the sandbox root."
        ),
    )


class GlobTool(RouteTool):
    name: str = "Find files by glob pattern"
    description: str = ""
    args_schema: Type[BaseModel] = GlobToolSchema

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._generate_description()

    def _run(self, **kwargs: Any) -> str:
        try:
            return self._run_impl(**kwargs)
        except Exception as e:
            logger.error("GlobTool failed unexpectedly: {}", e)
            return f"Error: failed to search for files. Unexpected exception: {e}"

    def _run_impl(self, **kwargs: Any) -> str:
        pattern = kwargs.get("pattern")
        if not pattern:
            return "Error: pattern argument is mandatory and was not given to the tool."

        path = kwargs.get("path") or "."

        search_root = self.construct_savepath(frompath=path)

        if not self.is_path_has_permission(search_root):
            return f"Error: path {path} is outside the allowed directory."

        if not search_root.exists():
            return f"Error: path {path} does not exist."

        if not search_root.is_dir():
            return f"Error: path {path} is not a directory."

        try:
            matches = list(search_root.glob(pattern))
        except (ValueError, NotImplementedError) as e:
            return f"Error: invalid glob pattern '{pattern}': {e}"

        files, error = self._collect_files_with_mtime(matches)
        if error:
            return error

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
            result += f"\n(showing {MAX_RESULTS} of {total} matches — narrow the pattern)"

        return result

    @staticmethod
    def _collect_files_with_mtime(
        matches: List[Path],
    ) -> Tuple[List[Tuple[Path, float]], str | None]:
        files: List[Tuple[Path, float]] = []
        for match in matches:
            try:
                if not match.is_file():
                    continue
                mtime = match.stat().st_mtime
            except OSError:
                continue
            files.append((match, mtime))
        return files, None
