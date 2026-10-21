import os


def write_all(descriptor: int, data: bytes) -> None:
    """Write all of `data`; `os.write` may write only part of it."""
    view = memoryview(data)
    while view:
        view = view[os.write(descriptor, view) :]
