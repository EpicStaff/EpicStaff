def main(
    file_path: str, old_string: str, new_string: str, replace_all: bool = False
) -> str:
    from epicstaff_storage import EpicStaffStorage

    if old_string == new_string:
        return "old_string and new_string are identical — no edit to make."

    storage = EpicStaffStorage()
    try:
        content = storage.read(file_path)
    except FileNotFoundError:
        return (
            f"File not found: {file_path}. Use s3_file_create_tool to create it first."
        )
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)

    occurrences = content.count(old_string)
    if occurrences == 0:
        return (
            f"old_string not found in {file_path} — no changes made. "
            "Check for an exact match, including whitespace."
        )
    if occurrences > 1 and not replace_all:
        return (
            f"old_string found {occurrences} times in {file_path} — it must be unique. "
            "Add more surrounding context to make it unique, or pass replace_all=true "
            "to replace every occurrence."
        )

    if replace_all:
        new_content = content.replace(old_string, new_string)
    else:
        new_content = content.replace(old_string, new_string, 1)

    try:
        storage.write(file_path, new_content)
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)

    if replace_all:
        return f"Replaced {occurrences} occurrence(s) of old_string in {file_path}."
    return f"Replaced 1 occurrence of old_string in {file_path}."
