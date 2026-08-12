_MAX_OUTPUT_CHARS = 30_000


def _format_flat(entry: dict, long: bool) -> str:
    marker = "/" if entry["type"] == "folder" else ""
    if not long:
        return f"{entry['name']}{marker}"
    modified = entry["modified"] or "-"
    return f"{entry['size']:>12}  {modified:<26}  {entry['name']}{marker}"


def _format_recursive(entry: dict, long: bool) -> str:
    if not long:
        return entry["path"]
    modified = entry["modified"] or "-"
    return f"{entry['size']:>12}  {modified:<26}  {entry['path']}"


def _cap(lines: list, total: int) -> str:
    text = "\n".join(lines)
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text

    truncated = []
    length = 0
    for line in lines:
        length += len(line) + 1
        if length > _MAX_OUTPUT_CHARS:
            break
        truncated.append(line)

    return (
        "\n".join(truncated)
        + f"\n... showing {len(truncated)} of {total} entries — narrow the path "
        "(or drop recursive) to see fewer entries."
    )


def main(path: str = "", recursive: bool = False, long: bool = False) -> str:
    from epicstaff_storage import EpicStaffStorage

    storage = EpicStaffStorage()
    try:
        entries = storage.walk(path) if recursive else storage.list(path)
    except FileNotFoundError:
        return f"Path not found: {path or '/'}"
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)

    if not entries:
        return f"No files or folders found under '{path or '/'}'."

    if recursive:
        entries = sorted(entries, key=lambda e: e["path"])
        lines = [_format_recursive(e, long) for e in entries]
    else:
        entries = sorted(entries, key=lambda e: (e["type"] != "folder", e["name"]))
        lines = [_format_flat(e, long) for e in entries]

    return _cap(lines, total=len(entries))
