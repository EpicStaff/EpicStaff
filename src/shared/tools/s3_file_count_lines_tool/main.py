def main(file_path: str) -> str:
    from epicstaff_storage import EpicStaffStorage
    from epicstaff_storage.storage import MAX_LINE_READ_BYTES

    storage = EpicStaffStorage()
    try:
        info = storage.info(file_path)
        if info["size"] > MAX_LINE_READ_BYTES:
            return (
                f"File '{file_path}' is {info['size']} bytes, exceeding the "
                f"{MAX_LINE_READ_BYTES // (1024 * 1024)} MB read limit — refusing to count it."
            )
        content = storage.read(file_path)
    except FileNotFoundError:
        return f"File not found: {file_path}."
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)

    lines = content.count("\n")
    words = len(content.split())
    size = info["size"]

    return f"{lines:>7} {words:>7} {size:>7} {file_path}"
