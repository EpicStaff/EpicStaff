# String Edit Tool
import os
from pathlib import Path
from typing import Optional, Tuple


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


def _context_snippet(text: str, edit_start_index: int) -> str:
    lines = text.split("\n")

    cumulative = 0
    line_no = len(lines) - 1
    for idx, line in enumerate(lines):
        line_len = len(line) + 1  # account for the stripped "\n"
        if cumulative + line_len > edit_start_index:
            line_no = idx
            break
        cumulative += line_len

    start = max(0, line_no - 1)
    end = min(len(lines), line_no + 2)
    return "\n".join(lines[start:end])


def main(
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> str:
    """
    Edit a file by exact string replacement. old_string must occur exactly
    once unless replace_all is set. Never raises: all failures are returned
    as readable error strings.
    """
    try:
        if not file_path:
            return (
                "Error: file_path argument is mandatory and was not given to the tool."
            )

        if old_string is None:
            return (
                "Error: old_string argument is mandatory and was not given to the tool."
            )

        if new_string is None:
            return (
                "Error: new_string argument is mandatory and was not given to the tool."
            )

        if old_string == new_string:
            return "Error: new_string must differ from old_string."

        replace_all = bool(replace_all)

        route_tool = RouteTool()
        file_savepath = route_tool.construct_savepath(frompath=file_path)

        if not RouteTool.is_path_has_permission(file_savepath):
            return f"Error: path {file_path} is outside the allowed directory."

        if not file_savepath.exists():
            return f"Error: file {file_path} does not exist."

        if file_savepath.is_dir():
            return f"Error: {file_path} is a directory, not a file."

        try:
            raw = file_savepath.read_bytes()
        except Exception as e:
            return f"Error: could not read file {file_path}: {e}"

        text, encoding = _decode_bytes(raw)
        if text is None:
            return (
                f"Error: could not decode {file_path} as text. It may be a binary file."
            )

        has_crlf = "\r\n" in text
        normalized_text = text.replace("\r\n", "\n")
        normalized_old = old_string.replace("\r\n", "\n")
        normalized_new = new_string.replace("\r\n", "\n")

        if not normalized_old:
            return "Error: old_string cannot be empty."

        count = normalized_text.count(normalized_old)

        if count == 0:
            return f"Error: old_string not found in {file_path}."

        if count > 1 and not replace_all:
            return (
                f"Error: old_string matches {count} locations in {file_path}. "
                "Add more surrounding context to make it unique, or pass replace_all=true "
                "to replace every occurrence."
            )

        first_index = normalized_text.index(normalized_old)

        if replace_all:
            new_normalized_text = normalized_text.replace(
                normalized_old, normalized_new
            )
            occurrences = count
        else:
            new_normalized_text = (
                normalized_text[:first_index]
                + normalized_new
                + normalized_text[first_index + len(normalized_old) :]
            )
            occurrences = 1

        context = _context_snippet(new_normalized_text, first_index)

        final_text = (
            new_normalized_text.replace("\n", "\r\n")
            if has_crlf
            else new_normalized_text
        )

        try:
            file_savepath.write_bytes(final_text.encode(encoding))
        except Exception as e:
            return f"Error: could not write file {file_path}: {e}"

        return f"Replaced {occurrences} occurrence(s) in {file_path}\n{context}"
    except Exception as e:
        return f"Error: failed to edit file. Unexpected exception: {e}"
