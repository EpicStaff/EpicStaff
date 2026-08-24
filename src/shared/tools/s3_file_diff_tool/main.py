_MAX_OUTPUT_CHARS = 30_000


def main(file_path_a: str, file_path_b: str) -> str:
    import difflib

    from epicstaff_storage import EpicStaffStorage

    storage = EpicStaffStorage()
    try:
        content_a = storage.read(file_path_a)
    except FileNotFoundError:
        return f"File not found: {file_path_a}."
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)

    try:
        content_b = storage.read(file_path_b)
    except FileNotFoundError:
        return f"File not found: {file_path_b}."
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)

    diff_lines = list(
        difflib.unified_diff(
            content_a.splitlines(keepends=True),
            content_b.splitlines(keepends=True),
            fromfile=file_path_a,
            tofile=file_path_b,
        )
    )

    if not diff_lines:
        return f"'{file_path_a}' and '{file_path_b}' are identical."

    text = "".join(diff_lines)
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text

    kept = []
    length = 0
    for line in diff_lines:
        length += len(line)
        if length > _MAX_OUTPUT_CHARS:
            break
        kept.append(line)

    return (
        "".join(kept)
        + f"\n... diff truncated at {_MAX_OUTPUT_CHARS} characters — narrow the "
        "comparison (e.g. smaller files) to see the full diff.\n"
    )
