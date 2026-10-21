import asyncio
import contextlib
import os


def write_all(descriptor: int, data: bytes) -> None:
    """Write all of `data`; `os.write` may write only part of it."""
    view = memoryview(data)
    while view:
        view = view[os.write(descriptor, view) :]


async def read_pipe(descriptor: int, max_bytes: int) -> bytes:
    """Read a pipe to its end without blocking the event loop; the descriptor is closed after.

    For the results a launcher helper writes. Returns b"" for more than `max_bytes`.
    """
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=max_bytes)
    pipe = os.fdopen(descriptor, "rb", buffering=0)
    transport, _ = await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), pipe)
    try:
        data = b""
        while chunk := await reader.read(max_bytes):
            data += chunk
            if len(data) > max_bytes:
                return b""
        return data
    finally:
        with contextlib.suppress(Exception):
            transport.close()
