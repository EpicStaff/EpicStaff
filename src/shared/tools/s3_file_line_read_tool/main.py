def main(file_path: str, offset: int = 1, limit: int = 2000) -> str:
    from epicstaff_storage import EpicStaffStorage
    from epicstaff_storage.storage import MAX_LINE_READ_BYTES

    if offset < 1:
        return f"offset must be >= 1 (1-based line number), got {offset}."
    if limit < 1:
        return f"limit must be >= 1, got {limit}."

    storage = EpicStaffStorage()
    try:
        info = storage.info(file_path)
        if info["size"] > MAX_LINE_READ_BYTES:
            return (
                f"File '{file_path}' is {info['size']} bytes, exceeding the "
                f"{MAX_LINE_READ_BYTES // (1024 * 1024)} MB read limit — refusing to read it in full. "
                "Use s3_file_count_lines_tool to check its size, or narrow offset/limit."
            )
        content = storage.read(file_path)
    except FileNotFoundError:
        return (
            f"File not found: {file_path}. Use s3_folder_list_tool to check the path."
        )
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)

    lines = content.split("\n")
    if offset > len(lines):
        return f"offset {offset} is out of range — {file_path} has {len(lines)} lines."

    end_index = min(offset - 1 + limit, len(lines))
    selected = lines[offset - 1 : end_index]

    return "\n".join(f"{i:>6}\t{line}" for i, line in enumerate(selected, start=offset))
