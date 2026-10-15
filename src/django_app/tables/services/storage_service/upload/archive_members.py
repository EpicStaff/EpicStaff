from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

from tables.services.storage_service.archive_unpacking.extraction import iter_archive_members
from tables.services.storage_service.archive_unpacking.extraction_guard import (
    ArchiveExtractionGuard,
)


class ArchiveMemberUploader:
    """Unpack one archive into storage under folder_key, a few PUTs in parallel.
    An instance serves one archive and is not reused: it holds that upload's state."""

    def __init__(
        self,
        backend,
        folder_key: str,
        guard: ArchiveExtractionGuard,
        *,
        workers: int,
        check_member: Callable[[str], None] | None = None,
    ):
        self._backend = backend
        self._folder_key = folder_key
        self._guard = guard
        self._workers = workers
        self._check_member = check_member
        # Every key goes here before its write starts, so a failure knows what to delete.
        self._started: list[str] = []
        self._pending: dict[str, Future] = {}
        self._written: dict[str, int] = {}

    def upload(self, archive_file) -> dict[str, int]:
        """Unpack archive_file into storage under folder_key; return {path in archive: size}.
        On any error, every key this call wrote or started is deleted before re-raising."""
        try:
            return self._upload_all(archive_file)
        except BaseException:
            # The pool has shut down by now, so no PUT can land after this delete.
            self._backend.discard_keys(self._started)
            raise

    def _upload_all(self, archive_file) -> dict[str, int]:
        """upload without cleanup; records each key in `_started` before writing it."""
        part_size = self._backend.part_size

        # Small members are sent from this pool, several at once.
        with ThreadPoolExecutor(
            max_workers=self._workers, thread_name_prefix="archive-put"
        ) as pool:
            try:
                # One member at a time: `reader` inflates its bytes only as they are read,
                # and the guard stops the loop once the real size passes the free space.
                for name, reader in iter_archive_members(archive_file, self._guard):
                    if self._check_member is not None:
                        self._check_member(name)
                    key = f"{self._folder_key}/{name}"
                    if name in self._pending:
                        # The same name twice in one archive: the later file must win.
                        self._pending.pop(name).result()

                    # Unpack up to one part plus a byte: this tells a small member from a large one.
                    head = _read_at_most(reader, part_size + 1)
                    if len(head) <= part_size:
                        # Small member: already whole in memory, send it with one PUT in the pool.
                        self._put_small(pool, name, key, head)
                    else:
                        # Large member: keep unpacking while it streams as multipart, part by part.
                        self._stream_large(name, key, head, reader)

                # Archive fully read: wait for the PUTs still running.
                for future in self._pending.values():
                    future.result()
            except BaseException:
                for future in self._pending.values():
                    future.cancel()
                raise

        return self._written

    def _put_small(self, pool: ThreadPoolExecutor, name: str, key: str, head: bytes) -> None:
        self._wait_for_free_worker()
        self._started.append(key)
        self._pending[name] = pool.submit(self._backend.put_bytes, key, head)
        self._written[name] = len(head)

    def _stream_large(self, name: str, key: str, head: bytes, reader) -> None:
        member = _ReplayingReader(head, reader)
        self._started.append(key)
        self._backend.upload_stream(key, member)
        self._written[name] = member.bytes_read

    def _wait_for_free_worker(self) -> None:
        """Block until fewer than `workers` uploads are running; re-raise any that failed."""
        while len(self._pending) >= self._workers:
            done, _ = wait(self._pending.values(), return_when=FIRST_COMPLETED)
            for name in [n for n, f in self._pending.items() if f in done]:
                self._pending.pop(name).result()


def _read_at_most(reader, limit: int) -> bytes:
    """Read from reader until EOF or `limit` bytes, whichever comes first."""
    parts: list[bytes] = []
    got = 0
    while got < limit:
        chunk = reader.read(limit - got)
        if not chunk:
            break
        parts.append(chunk)
        got += len(chunk)
    return b"".join(parts)


class _ReplayingReader:
    """File-like reader that replays the already-read head, then the rest of the member.
    read(n) returns exactly n bytes until EOF: S3 rejects a short part mid-upload."""

    def __init__(self, head: bytes, rest):
        self._head = head
        self._rest = rest
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            out, self._head = self._head + self._rest.read(), b""
        else:
            out, self._head = self._head[:size], self._head[size:]
            if len(out) < size:
                out += _read_at_most(self._rest, size - len(out))
        self.bytes_read += len(out)
        return out
