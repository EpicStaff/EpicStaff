_MAX_MATCHES = 250
_MAX_OUTPUT_CHARS = 30_000


def _cap_lines(lines: list, max_chars: int) -> tuple[str, bool]:
    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text, False

    kept = []
    length = 0
    for line in lines:
        length += len(line) + 1
        if length > max_chars:
            break
        kept.append(line)
    return "\n".join(kept), True


def _skip_note(skipped_large: int, skipped_binary: int) -> str:
    parts = []
    if skipped_large:
        parts.append(f"{skipped_large} file(s) skipped (exceeds size limit)")
    if skipped_binary:
        parts.append(f"{skipped_binary} file(s) skipped (binary/non-utf8)")
    if not parts:
        return ""
    return " (" + "; ".join(parts) + ")"


def main(
    pattern: str,
    path: str = "",
    recursive: bool = True,
    ignore_case: bool = False,
    show_line_numbers: bool = True,
    files_with_matches: bool = False,
) -> str:
    import re

    from epicstaff_storage import EpicStaffStorage
    from epicstaff_storage.storage import MAX_LINE_READ_BYTES

    try:
        regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as e:
        return f"Invalid regex pattern '{pattern}': {e}"

    storage = EpicStaffStorage()
    is_probably_folder = path == "" or path.endswith("/")
    try:
        candidates: list[dict] | None = None
        if not is_probably_folder:
            try:
                info = storage.info(path)
                candidates = [{"path": path, "size": info["size"]}]
            except FileNotFoundError:
                candidates = None

        if candidates is None:
            if recursive:
                candidates = [
                    {"path": e["path"], "size": e["size"]} for e in storage.walk(path)
                ]
            else:
                prefix = path.rstrip("/")
                candidates = [
                    {
                        "path": f"{prefix}/{e['name']}" if prefix else e["name"],
                        "size": e["size"],
                    }
                    for e in storage.list(path)
                    if e["type"] == "file"
                ]
    except FileNotFoundError:
        return f"Path not found: {path or '/'}"
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)

    if not candidates:
        return f"No files found under '{path or '/'}'."

    matches: list[str] = []
    matched_files: set[str] = set()
    skipped_large = 0
    skipped_binary = 0
    match_cap_hit = False

    for entry in candidates:
        if entry["size"] > MAX_LINE_READ_BYTES:
            skipped_large += 1
            continue

        try:
            content = storage.read(entry["path"])
        except FileNotFoundError:
            continue
        except UnicodeDecodeError:
            skipped_binary += 1
            continue
        except PermissionError as e:
            return str(e)
        except ValueError as e:
            return str(e)
        except RuntimeError as e:
            return str(e)

        if files_with_matches:
            if regex.search(content):
                matched_files.add(entry["path"])
            continue

        for line_number, line in enumerate(content.split("\n"), start=1):
            if len(matches) >= _MAX_MATCHES:
                match_cap_hit = True
                break
            if regex.search(line):
                if show_line_numbers:
                    matches.append(f"{entry['path']}:{line_number}: {line}")
                else:
                    matches.append(f"{entry['path']}: {line}")

        if match_cap_hit:
            break

    skip_note = _skip_note(skipped_large, skipped_binary)

    if files_with_matches:
        if not matched_files:
            return f"No matches for pattern '{pattern}'.{skip_note}"
        text, char_truncated = _cap_lines(sorted(matched_files), _MAX_OUTPUT_CHARS)
        if char_truncated:
            text += (
                "\n... output truncated — narrow the path or pattern to see the rest."
            )
        return text + skip_note

    if not matches:
        return f"No matches for pattern '{pattern}'.{skip_note}"

    text, char_truncated = _cap_lines(matches, _MAX_OUTPUT_CHARS)
    if match_cap_hit or char_truncated:
        text += (
            f"\n... showing partial results (cap {_MAX_MATCHES} matches / "
            f"{_MAX_OUTPUT_CHARS} chars) — narrow path or pattern to see more."
        )
    return text + skip_note
