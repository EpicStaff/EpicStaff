# Grep Tool
import fnmatch
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEFAULT_HEAD_LIMIT = 250
MAX_CONTEXT_LINES = 10

# A per-file match record: (relative_path, {0-based lineno: line text}, matched linenos)
FileMatch = Tuple[str, Dict[int, str], List[int]]


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


def _decode_bytes(raw: bytes) -> Tuple[Optional[str], Optional[str]]:
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    try:
        from charset_normalizer import from_bytes

        match = from_bytes(raw).best()
        if match is None:
            return None, None
        return str(match), match.encoding
    except Exception:
        return None, None


def _looks_binary(raw: bytes) -> bool:
    return b"\x00" in raw[:8192]


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

    resolved_root = (
        search_root.resolve() if search_root.is_dir() else search_root.parent.resolve()
    )

    matched: List[Path] = []
    for candidate in candidates:
        if fnmatch.fnmatch(candidate.name, glob_filter):
            matched.append(candidate)
            continue

        try:
            rel_posix = candidate.resolve().relative_to(resolved_root).as_posix()
        except (ValueError, OSError):
            continue

        if fnmatch.fnmatch(rel_posix, glob_filter):
            matched.append(candidate)

    return matched


def _search_with_python(
    *,
    pattern: str,
    search_root: Path,
    glob_filter: str | None,
    case_insensitive: bool,
    context_lines: int,
) -> Tuple[List[FileMatch], Optional[str]]:
    flags = re.IGNORECASE if case_insensitive else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return [], f"Error: invalid regex: {e}"

    candidate_files = _iter_candidate_files(search_root, glob_filter)
    resolved_root = search_root.resolve()

    matches: List[FileMatch] = []

    for file_path in candidate_files:
        try:
            raw = file_path.read_bytes()
        except OSError:
            continue

        if _looks_binary(raw):
            continue

        text, _encoding = _decode_bytes(raw)
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
            continue

        matches.append((rel, line_map, matched_linenos))

    return matches, None


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

    rendered = []
    for rel, line_map, _matched in matches:
        for lineno in sorted(line_map.keys()):
            rendered.append(f"{rel}:{lineno + 1}:{line_map[lineno]}")
    return rendered, len(rendered)


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


def main(
    pattern: str,
    path: str | None = None,
    glob: str | None = None,
    output_mode: str = "files_with_matches",
    case_insensitive: bool = False,
    context_lines: int = 0,
    head_limit: int = 250,
) -> str:
    """
    Search file contents by regular expression (pure-Python backend — no
    external `rg` binary is available in the sandbox). Never raises: all
    failures are returned as readable error strings.
    """
    try:
        if not pattern:
            return "Error: pattern argument is mandatory and was not given to the tool."

        path = path or "."
        output_mode = output_mode or "files_with_matches"
        case_insensitive = bool(case_insensitive)
        context_lines = context_lines or 0
        head_limit = head_limit or DEFAULT_HEAD_LIMIT

        if output_mode not in ("files_with_matches", "content", "count"):
            return (
                f"Error: invalid output_mode '{output_mode}'. Use one of "
                "files_with_matches, content, count."
            )

        if context_lines < 0 or context_lines > MAX_CONTEXT_LINES:
            return f"Error: context_lines must be between 0 and {MAX_CONTEXT_LINES}."

        route_tool = RouteTool()
        search_root = route_tool.construct_savepath(frompath=path)

        if not RouteTool.is_path_has_permission(search_root):
            return f"Error: path {path} is outside the allowed directory."

        if not search_root.exists():
            return f"Error: path {path} does not exist."

        matches, error = _search_with_python(
            pattern=pattern,
            search_root=search_root,
            glob_filter=glob,
            case_insensitive=case_insensitive,
            context_lines=context_lines if output_mode == "content" else 0,
        )

        if error:
            return error

        lines, total_entries = _render(matches, output_mode)
        return _format_result(pattern, lines, total_entries, head_limit)
    except Exception as e:
        return f"Error: failed to search files. Unexpected exception: {e}"
