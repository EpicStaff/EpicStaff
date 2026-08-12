_MAX_RESULTS = 100


def main(pattern: str, path: str = "") -> str:
    import fnmatch

    from epicstaff_storage import EpicStaffStorage

    storage = EpicStaffStorage()
    try:
        entries = storage.walk(path)
    except FileNotFoundError:
        return f"Path not found: {path or '/'}"
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)

    matched = [e for e in entries if fnmatch.fnmatchcase(e["path"], pattern)]
    if not matched:
        return f"No files matching pattern '{pattern}' under '{path or '/'}'."

    with_modified = [e for e in matched if e["modified"] is not None]
    without_modified = [e for e in matched if e["modified"] is None]
    with_modified.sort(key=lambda e: e["modified"], reverse=True)
    ordered = with_modified + without_modified

    total = len(ordered)
    capped = ordered[:_MAX_RESULTS]
    lines = [e["path"] for e in capped]

    result = "\n".join(lines)
    if total > _MAX_RESULTS:
        result += (
            f"\n... showing {_MAX_RESULTS} of {total} matches — narrow the pattern "
            "or path to see fewer results."
        )
    return result
