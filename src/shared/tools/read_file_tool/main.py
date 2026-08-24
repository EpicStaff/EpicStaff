# Read File Tool
import difflib
import os
from pathlib import Path
from typing import List, Optional, Tuple

MAX_LINES = 2000
MAX_LINE_CHARS = 2000
MAX_PDF_PAGES = 20
MAX_RAW_BYTES = 256 * 1024
PDF_PAGES_REQUIRED_THRESHOLD = 10


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


def _suggest_similar(file_savepath: Path) -> Optional[str]:
    parent = file_savepath.parent
    if not parent.exists() or not parent.is_dir():
        return None

    target_name = file_savepath.name.lower()
    best_name = None
    best_score = 0.0
    try:
        for candidate in parent.iterdir():
            if not candidate.is_file():
                continue
            score = difflib.SequenceMatcher(
                None, target_name, candidate.name.lower()
            ).ratio()
            if score > best_score:
                best_score = score
                best_name = candidate.name
    except OSError:
        return None

    if best_name is not None and best_score >= 0.6:
        return best_name
    return None


def _read_text(file_savepath: Path, file_path: str, offset: int, limit: int) -> str:
    try:
        raw = file_savepath.read_bytes()
    except Exception as e:
        return f"Error: could not read file {file_path}: {e}"

    if len(raw) == 0:
        return "Warning: file exists but is empty"

    truncated_raw = False
    if len(raw) > MAX_RAW_BYTES:
        raw = raw[:MAX_RAW_BYTES]
        truncated_raw = True

    text, _encoding = _decode_bytes(raw)
    if text is None:
        return (
            f"Error: could not decode {file_path} as text. "
            "It may be a binary file — this tool only reads text, PDF, and .ipynb files."
        )

    lines = text.splitlines()
    total_lines = len(lines)

    if total_lines > 0 and offset > total_lines:
        return (
            f"Error: offset {offset} is beyond the end of the file "
            f"({total_lines} lines). Use a smaller offset."
        )

    selected = lines[offset - 1 : offset - 1 + limit]

    rendered = []
    for idx, line in enumerate(selected, start=offset):
        if len(line) > MAX_LINE_CHARS:
            line = line[:MAX_LINE_CHARS] + "…"
        rendered.append(f"{idx:6d}\t{line}")

    result = "\n".join(rendered)

    end_line = offset - 1 + len(selected)
    notes = []
    if end_line < total_lines:
        notes.append(
            f"(showing lines {offset}-{end_line} of {total_lines} — output truncated, "
            "pass a larger offset to continue reading)"
        )
    if truncated_raw:
        notes.append(
            f"(raw file content truncated to {MAX_RAW_BYTES} bytes before line splitting)"
        )

    if notes:
        result = f"{result}\n" + "\n".join(notes)

    return result


def _parse_pages(
    pages: str, total_pages: int
) -> Tuple[Optional[List[int]], Optional[str]]:
    pages = pages.strip()
    page_numbers: List[int] = []
    try:
        for part in pages.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                start_str, end_str = part.split("-", 1)
                start, end = int(start_str), int(end_str)
                if start > end:
                    return (
                        None,
                        f"Error: invalid page range '{part}' — start must be <= end.",
                    )
                page_numbers.extend(range(start, end + 1))
            else:
                page_numbers.append(int(part))
    except ValueError:
        return (
            None,
            f"Error: could not parse pages argument '{pages}'. Use formats like "
            '"1-5", "3", or "10-20".',
        )

    for page_number in page_numbers:
        if page_number < 1 or page_number > total_pages:
            return (
                None,
                f"Error: page {page_number} is out of range "
                f"(document has {total_pages} pages).",
            )

    seen = set()
    deduped: List[int] = []
    for page_number in page_numbers:
        if page_number not in seen:
            seen.add(page_number)
            deduped.append(page_number)

    return deduped, None


def _render_notebook_output(output: dict) -> str:
    output_type = output.get("output_type")
    if output_type == "stream":
        text = output.get("text", "")
        return text if isinstance(text, str) else "".join(text)
    if output_type in ("execute_result", "display_data"):
        data = output.get("data", {})
        if "text/plain" in data:
            text = data["text/plain"]
            return text if isinstance(text, str) else "".join(text)
        return "[non-text output omitted]"
    if output_type == "error":
        traceback = output.get("traceback", [])
        return "\n".join(traceback)
    return "[non-text output omitted]"


def _read_pdf(file_savepath: Path, pages: Optional[str]) -> str:
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(str(file_savepath))
    except Exception as e:
        return f"Error: could not open PDF {file_savepath.name}: {e}"

    try:
        total_pages = len(pdf)

        if pages is None:
            if total_pages > PDF_PAGES_REQUIRED_THRESHOLD:
                return (
                    f"Error: {file_savepath.name} has {total_pages} pages, which is more "
                    'than 10. Pass the \'pages\' argument (e.g. "1-5" or "3") to select '
                    "which pages to read."
                )
            page_numbers = list(range(1, total_pages + 1))
        else:
            page_numbers, error = _parse_pages(pages, total_pages)
            if error:
                return error

        truncation_note = ""
        if len(page_numbers) > MAX_PDF_PAGES:
            truncation_note = (
                f"\n(showing {MAX_PDF_PAGES} of {len(page_numbers)} requested pages — "
                "narrow the 'pages' argument to see the rest)"
            )
            page_numbers = page_numbers[:MAX_PDF_PAGES]

        rendered = []
        for page_number in page_numbers:
            page = pdf.get_page(page_number - 1)
            try:
                text_page = page.get_textpage()
                try:
                    page_text = text_page.get_text_range()
                finally:
                    text_page.close()
            finally:
                page.close()
            rendered.append(f"=== page {page_number} ===\n{page_text}")

        return "\n\n".join(rendered) + truncation_note
    except Exception as e:
        return f"Error: failed to extract text from PDF {file_savepath.name}: {e}"
    finally:
        pdf.close()


def _read_notebook(file_savepath: Path) -> str:
    import nbformat

    try:
        nb = nbformat.read(str(file_savepath), as_version=4)
    except Exception as e:
        return f"Error: could not parse notebook {file_savepath.name}: {e}"

    if not nb.cells:
        return "Warning: file exists but is empty"

    rendered = []
    for idx, cell in enumerate(nb.cells):
        cell_type = cell.get("cell_type", "code")
        source = cell.get("source", "")
        block = [f"[cell {idx}: {cell_type}]", source]

        if cell_type == "code":
            for output in cell.get("outputs", []):
                block.append(_render_notebook_output(output))

        rendered.append("\n".join(part for part in block if part))

    return "\n\n".join(rendered)


def main(
    file_path: str,
    offset: int = 1,
    limit: int = 2000,
    pages: str | None = None,
) -> str:
    """
    Read a file's content — plain text (with offset/limit), PDF (page ranges),
    or Jupyter notebook. Never raises: all failures are returned as readable
    error strings.
    """
    try:
        if not file_path:
            return (
                "Error: file_path argument is mandatory and was not given to the tool."
            )

        offset = offset or 1
        limit = limit or MAX_LINES

        if offset < 1:
            return (
                f"Error: offset must be >= 1, got {offset}. Fix the offset and retry."
            )
        if limit < 1:
            return f"Error: limit must be >= 1, got {limit}. Fix the limit and retry."
        if limit > MAX_LINES:
            limit = MAX_LINES

        route_tool = RouteTool()
        file_savepath = route_tool.construct_savepath(frompath=file_path)

        if not RouteTool.is_path_has_permission(file_savepath):
            return f"Error: path {file_path} is outside the allowed directory."

        if file_savepath.is_dir():
            return (
                f"Error: {file_path} is a directory, not a file. "
                "Use GlobTool or FolderTool to list its contents."
            )

        if not file_savepath.exists():
            suggestion = _suggest_similar(file_savepath)
            suffix = f" Did you mean '{suggestion}'?" if suggestion else ""
            return f"Error: file {file_path} does not exist.{suffix}"

        suffix = file_savepath.suffix.lower()

        if suffix == ".pdf":
            return _read_pdf(file_savepath, pages)
        if suffix == ".ipynb":
            return _read_notebook(file_savepath)
        return _read_text(file_savepath, file_path, offset, limit)
    except Exception as e:
        return f"Error: failed to read file. Unexpected exception: {e}"
