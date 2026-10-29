"""The dump's chunks are written in a thread, and the descriptor outlives every write to it."""

import asyncio
import hashlib
import os
import threading
import time
import uuid

from src.shared.models.plugin_nodes import DesiredDatabase, DesiredDatabaseServer, database_names_for

from es_plugins.database.backup_service import BackupService

CHUNK = b"d" * (1024 * 1024)


def desired() -> DesiredDatabase:
    names = database_names_for("weather")
    return DesiredDatabase(
        server=DesiredDatabaseServer(name="plugins_db", host="plugins_db", port=5432),
        installation_id=uuid.uuid4().hex,
        database_name=names.database,
        owner_role=names.owner_role,
        app_role=names.app_role,
        job_role=names.job_role,
        connection_limit=3,
        statement_timeout_seconds=10,
    )


class FeedingClient:
    """Stands in for pg_dump: hands its chunks to the sink, then waits to be ended."""

    def __init__(self, chunks: list[bytes], *, then_wait: bool = False):
        self._chunks = chunks
        self._then_wait = then_wait

    async def run(self, tool, arguments, *, login, stdout):
        for chunk in self._chunks:
            if not await stdout(chunk):
                return
        if self._then_wait:
            await asyncio.sleep(60)


def service(client) -> BackupService:
    return BackupService(None, client, None, None, "backup-password")


async def test_the_chunks_reach_the_file_whole_and_are_hashed(tmp_path):
    chunks = [CHUNK, b"tail"]
    descriptor = os.open(tmp_path / "dump", os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        size, sha256 = await service(FeedingClient(chunks))._dump(desired(), descriptor, room=10 * len(CHUNK))
    finally:
        os.close(descriptor)

    content = (tmp_path / "dump").read_bytes()
    assert content == b"".join(chunks)
    assert (size, sha256) == (len(content), hashlib.sha256(content).hexdigest())


def drain_later(read_end: int, byte_count: int, delay: float) -> threading.Thread:
    def drain():
        time.sleep(delay)
        read = 0
        while read < byte_count:
            read += len(os.read(read_end, byte_count))

    thread = threading.Thread(target=drain)
    thread.start()
    return thread


async def test_the_event_loop_runs_while_a_write_blocks():
    read_end, write_end = os.pipe()
    # The pipe holds far less than a chunk: the write blocks until the thread reads it.
    drainer = drain_later(read_end, len(CHUNK), delay=0.5)
    try:
        dump = asyncio.create_task(service(FeedingClient([CHUNK]))._dump(desired(), write_end, room=len(CHUNK)))
        started = time.monotonic()
        for _ in range(5):
            await asyncio.sleep(0.01)
        ticked_after = time.monotonic() - started

        assert ticked_after < 0.4
        assert not dump.done()
        assert (await dump)[0] == len(CHUNK)
    finally:
        drainer.join()
        os.close(read_end)
        os.close(write_end)


async def test_a_cancel_during_a_write_returns_only_once_the_write_is_done():
    read_end, write_end = os.pipe()
    drainer = drain_later(read_end, len(CHUNK), delay=0.6)
    try:
        dump = asyncio.create_task(
            service(FeedingClient([CHUNK], then_wait=True))._dump(desired(), write_end, room=len(CHUNK))
        )
        await asyncio.sleep(0.1)
        dump.cancel()
        await asyncio.sleep(0.2)
        # The thread still writes to the descriptor: the dump has not let the caller close it.
        assert not dump.done()

        await asyncio.to_thread(drainer.join)
        await asyncio.wait({dump}, timeout=5)

        assert dump.cancelled()
    finally:
        drainer.join()
        os.close(read_end)
        os.close(write_end)
