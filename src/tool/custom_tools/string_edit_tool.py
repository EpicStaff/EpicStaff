from pathlib import Path
from typing import Any, Type

from loguru import logger
from pydantic import BaseModel, Field

from ._text_utils import decode_bytes
from .route_tool import RouteTool


class StringEditToolSchema(BaseModel):
    """Input for StringEditTool."""

    file_path: str = Field(
        ..., description="Path to the file to edit, relative to the sandbox root."
    )
    old_string: str = Field(
        ..., description="Exact text to find. May be multi-line. Matched verbatim, no regex."
    )
    new_string: str = Field(
        ..., description="Replacement text. Must differ from old_string."
    )
    replace_all: bool = Field(
        False,
        description="Replace every occurrence of old_string instead of requiring exactly one match.",
    )


class StringEditTool(RouteTool):
    name: str = "Edit a file by exact string replacement"
    description: str = ""
    args_schema: Type[BaseModel] = StringEditToolSchema

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._generate_description()

    def _run(self, **kwargs: Any) -> str:
        try:
            return self._run_impl(**kwargs)
        except Exception as e:
            logger.error("StringEditTool failed unexpectedly: {}", e)
            return f"Error: failed to edit file. Unexpected exception: {e}"

    def _run_impl(self, **kwargs: Any) -> str:
        file_path = kwargs.get("file_path")
        if not file_path:
            return "Error: file_path argument is mandatory and was not given to the tool."

        old_string = kwargs.get("old_string")
        if old_string is None:
            return "Error: old_string argument is mandatory and was not given to the tool."

        new_string = kwargs.get("new_string")
        if new_string is None:
            return "Error: new_string argument is mandatory and was not given to the tool."

        if old_string == new_string:
            return "Error: new_string must differ from old_string."

        replace_all = bool(kwargs.get("replace_all", False))

        file_savepath = self.construct_savepath(frompath=file_path)

        if not self.is_path_has_permission(file_savepath):
            return f"Error: path {file_path} is outside the allowed directory."

        if not file_savepath.exists():
            return f"Error: file {file_path} does not exist."

        if file_savepath.is_dir():
            return f"Error: {file_path} is a directory, not a file."

        try:
            raw = file_savepath.read_bytes()
        except Exception as e:
            return f"Error: could not read file {file_path}: {e}"

        text, encoding = decode_bytes(raw)
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
            new_normalized_text = normalized_text.replace(normalized_old, normalized_new)
            occurrences = count
        else:
            new_normalized_text = (
                normalized_text[:first_index]
                + normalized_new
                + normalized_text[first_index + len(normalized_old) :]
            )
            occurrences = 1

        context = self._context_snippet(new_normalized_text, first_index)

        final_text = (
            new_normalized_text.replace("\n", "\r\n") if has_crlf else new_normalized_text
        )

        try:
            file_savepath.write_bytes(final_text.encode(encoding))
        except Exception as e:
            return f"Error: could not write file {file_path}: {e}"

        return f"Replaced {occurrences} occurrence(s) in {file_path}\n{context}"

    @staticmethod
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
