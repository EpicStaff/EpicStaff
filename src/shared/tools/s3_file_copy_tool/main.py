def main(src: str, dst: str) -> str:
    from epicstaff_storage import EpicStaffStorage

    try:
        EpicStaffStorage().copy(src, dst)
        return f"File copied from {src} to {dst} successfully."
    except FileNotFoundError:
        return f"Source file {src} not found."
    except PermissionError as e:
        return str(e)
