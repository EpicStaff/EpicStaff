def main(path: str) -> str:
    from epicstaff_storage import EpicStaffStorage

    storage = EpicStaffStorage()
    try:
        try:
            storage.info(path)
            return f"'{path}' exists (file)."
        except FileNotFoundError:
            pass

        if storage.exists(path):
            return f"'{path}' exists (folder)."

        return f"'{path}' does not exist."
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)
