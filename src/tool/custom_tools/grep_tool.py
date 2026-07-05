import fnmatch
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Literal, Tuple, Type

from loguru import logger
from pydantic import BaseModel, Field

from ._text_utils import decode_bytes
from .route_tool import RouteTool

DEFAULT_HEAD_LIMIT = 250
MAX_CONTEXT_LINES = 10
RG_TIMEOUT_SECONDS = 30

# A per-file match record: (relative_path, {0-based lineno: line text}, matched linenos)
FileMatch = Tuple[str, Dict[int, str], List[int]]


class GrepToolSchema(BaseModel):
    """Input for GrepTool."""

    pattern: str = Field(..., description="Regular expression to search for.")
    path: str | None = Field(
        None,
        description=(
            "File or directory to search in, relative to the sandbox root. "
            "Defaults to the sandbox root."
        ),
    )
    glob: str | None = Field(
        None,
        description="Filename filter, e.g. '*.log' or '*.{ts,tsx}'.",
    )
    output_mode: Literal["files_with_matches", "content", "count"] = Field(
        "files_with_matches",
        description=(
            "files_with_matches: list matching file paths. content: matching "
            "lines with context. count: number of matching lines per file."
        ),
    )
    case_insensitive: bool = Field(False, description="Case-insensitive search.")
    context_lines: int = Field(
        0,
        ge=0,
        le=MAX_CONTEXT_LINES,
        description="Lines of context around each match (content mode only). 0-10.",
    )
    head_limit: int = Field(
        DEFAULT_HEAD_LIMIT,
        ge=1,
        description="Maximum output lines/entries to return. Default 250.",
    )


class GrepTool(RouteTool):
    name: str = "Search file contents by regular expression"
    description: str = ""
    args_schema: Type[BaseModel] = GrepToolSchema

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._generate_description()

    def _run(self, **kwargs: Any) -> str:
        try:
            return self._run_impl(**kwargs)
        except Exception as e:
            logger.error("GrepTool failed unexpectedly: {}", e)
            return f"Error: failed to search files. Unexpected exception: {e}"

    def _run_impl(self, **kwargs: Any) -> str:
        pattern = kwargs.get("pattern")
        if not pattern:
            return "Error: pattern argument is mandatory and was not given to the tool."

        path = kwargs.get("path") or "."
        glob_filter = kwargs.get("glob")
        output_mode = kwargs.get("output_mode") or "files_with_matches"
        case_insensitive = bool(kwargs.get("case_insensitive", False))
        context_lines = kwargs.get("context_lines") or 0
        head_limit = kwargs.get("head_limit") or DEFAULT_HEAD_LIMIT

        if output_mode not in ("files_with_matches", "content", "count"):
            return (
                f"Error: invalid output_mode '{output_mode}'. Use one of "
                "files_with_matches, content, count."
            )

        if context_lines < 0 or context_lines > MAX_CONTEXT_LINES:
            return f"Error: context_lines must be between 0 and {MAX_CONTEXT_LINES}."

        search_root = self.construct_savepath(frompath=path)

        if not self.is_path_has_permission(search_root):
            return f"Error: path {path} is outside the allowed directory."

        if not search_root.exists():
            return f"Error: path {path} does not exist."

        if shutil.which("rg"):
            logger.info("GrepTool using ripgrep backend")
            matches, error = self._search_with_rg(
                pattern=pattern,
                search_root=search_root,
                glob_filter=glob_filter,
                case_insensitive=case_insensitive,
                context_lines=context_lines if output_mode == "content" else 0,
            )
        else:
            logger.info("GrepTool using pure-Python fallback backend (rg not on PATH)")
            matches, error = self._search_with_python(
                pattern=pattern,
                search_root=search_root,
                glob_filter=glob_filter,
                case_insensitive=case_insensitive,
                context_lines=context_lines if output_mode == "content" else 0,
            )

        if error:
            return error

        lines, total_entries = self._render(matches, output_mode)
        return self._format_result(pattern, lines, total_entries, head_limit)

    # ------------------------------------------------------------------
    # Shared output formatting (used by both backends)
    # ------------------------------------------------------------------

    @staticmethod
    def _render(matches: List[FileMatch], output_mode: str) -> Tuple[List[str], int]:
        if not matches:
            return [], 0

        matches = sorted(matches, key=lambda item: item[0])

        if output_mode == "files_with_matches":
            rendered = [rel for rel, _line_map, _matched in matches]
            return rendered, len(rendered)

        if output_mode == "count":
            rendered = [f"{rel}:{len(matched)}" for rel, _line_map, matched in matches]
            total = sum(len(matched) for _rel, _line_map, matched in matches)
            rendered.append(f"total:{total}")
            return rendered, len(rendered) - 1

        # content mode: emit every line we captured (matches + context), in
        # ascending line-number order, one output line per source line.
        rendered = []
        for rel, line_map, _matched in matches:
            for lineno in sorted(line_map.keys()):
                rendered.append(f"{rel}:{lineno + 1}:{line_map[lineno]}")
        return rendered, len(rendered)

    @staticmethod
    def _format_result(
        pattern: str, lines: List[str], total_entries: int, head_limit: int
    ) -> str:
        if total_entries == 0:
            return f"No matches for pattern {pattern}"

        capped = lines[:head_limit]
        result = "\n".join(capped)

        if len(lines) > head_limit:
            result += (
                f"\n(showing first {head_limit} of {len(lines)} lines — "
                "narrow the pattern, path, or glob to see more)"
            )

        return result

    # ------------------------------------------------------------------
    # ripgrep backend
    # ------------------------------------------------------------------

    def _search_with_rg(
        self,
        *,
        pattern: str,
        search_root: Path,
        glob_filter: str | None,
        case_insensitive: bool,
        context_lines: int,
    ) -> Tuple[List[FileMatch], str | None]:
        args = ["rg", "--no-ignore", "--json"]

        if case_insensitive:
            args.append("-i")

        if glob_filter:
            args.extend(["--glob", glob_filter])

        if context_lines > 0:
            args.extend(["--context", str(context_lines)])

        args.extend(["--", pattern, str(search_root)])

        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=RG_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return (
                [],
                (
                    f"Error: search timed out after {RG_TIMEOUT_SECONDS}s. "
                    "Narrow the path or glob and try again."
                ),
            )
        except OSError as e:
            return [], f"Error: failed to invoke ripgrep: {e}"

        if proc.returncode not in (0, 1):
            stderr = proc.stderr.strip() or "unknown ripgrep error"
            return [], f"Error: invalid regex: {stderr}"

        matches = self._parse_rg_json(proc.stdout, search_root)
        return matches, None

    @staticmethod
    def _parse_rg_json(stdout: str, search_root: Path) -> List[FileMatch]:
        per_file: Dict[str, Tuple[Dict[int, str], List[int]]] = {}
        current_path: str | None = None
        resolved_root = search_root.resolve()

        for raw_line in stdout.splitlines():
            if not raw_line:
                continue
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")
            data = event.get("data", {})

            if event_type == "begin":
                text_path = data.get("path", {}).get("text")
                try:
                    current_path = str(Path(text_path).resolve().relative_to(resolved_root))
                except (ValueError, OSError, TypeError):
                    current_path = text_path
                per_file.setdefault(current_path, ({}, []))
            elif event_type in ("match", "context"):
                if current_path is None:
                    continue
                line_map, matched = per_file.setdefault(current_path, ({}, []))
                lineno = data.get("line_number")
                text = data.get("lines", {}).get("text", "")
                if lineno is None:
                    continue
                line_map[lineno - 1] = text.rstrip("\n")
                if event_type == "match":
                    matched.append(lineno - 1)
            elif event_type == "end":
                current_path = None

        return [
            (rel, line_map, matched)
            for rel, (line_map, matched) in per_file.items()
            if matched
        ]

    # ------------------------------------------------------------------
    # pure-Python fallback backend
    # ------------------------------------------------------------------

    def _search_with_python(
        self,
        *,
        pattern: str,
        search_root: Path,
        glob_filter: str | None,
        case_insensitive: bool,
        context_lines: int,
    ) -> Tuple[List[FileMatch], str | None]:
        flags = re.IGNORECASE if case_insensitive else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return [], f"Error: invalid regex: {e}"

        candidate_files = self._iter_candidate_files(search_root, glob_filter)
        resolved_root = search_root.resolve()

        matches: List[FileMatch] = []

        for file_path in candidate_files:
            try:
                raw = file_path.read_bytes()
            except OSError:
                continue

            if self._looks_binary(raw):
                continue

            text, _encoding = decode_bytes(raw)
            if text is None:
                continue

            file_lines = text.splitlines()
            matched_linenos = [
                idx for idx, file_line in enumerate(file_lines) if regex.search(file_line)
            ]
            if not matched_linenos:
                continue

            line_map: Dict[int, str] = {}
            for lineno in matched_linenos:
                start = max(0, lineno - context_lines)
                end = min(len(file_lines), lineno + context_lines + 1)
                for idx in range(start, end):
                    line_map[idx] = file_lines[idx]

            try:
                rel = str(file_path.resolve().relative_to(resolved_root))
            except (ValueError, OSError):
                rel = str(file_path)

            matches.append((rel, line_map, matched_linenos))

        return matches, None

    @staticmethod
    def _iter_candidate_files(search_root: Path, glob_filter: str | None) -> List[Path]:
        if search_root.is_file():
            candidates = [search_root]
        else:
            candidates = []
            for dirpath, _dirnames, filenames in os.walk(search_root):
                for filename in filenames:
                    candidates.append(Path(dirpath) / filename)

        if not glob_filter:
            return candidates

        return [c for c in candidates if fnmatch.fnmatch(c.name, glob_filter)]

    @staticmethod
    def _looks_binary(raw: bytes) -> bool:
        return b"\x00" in raw[:8192]
