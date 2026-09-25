from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

from tables.services.storage_service.archive_limits import ArchiveExtractionGuard
from utils.logger import logger


def upload_archive_members(
    archive_file, guard: ArchiveExtractionGuard, backend, folder_key: str, *, part_size, workers
) -> dict[str, int]:
    """Unpack archive_file into storage under folder_key; returns {path in archive: size}.

    Files are read one after another (zip/tar can't be read in parallel), but
    their uploads overlap in a pool of `workers`. A file up to part_size is
    sent from memory in one PUT, a bigger one is streamed, so RAM stays near
    workers x part_size. On any error the PUTs already running finish first,
    then every key this call wrote (or started to) is deleted again, so nothing
    it created is left behind; the error is re-raised."""
    started: list[str] = []
    try:
        return _upload_members(
            archive_file, guard, backend, folder_key, part_size, workers, started
        )
    except BaseException:
        # The pool has shut down by now, so no PUT can land after this delete.
        discard_keys(backend, started)
        raise


def discard_keys(backend, keys: list[str]) -> None:
    """Remove exactly these keys of an upload that failed. A failure is only
    logged, so the caller re-raises the error that made the upload fail."""
    if not keys:
        return
    try:
        # One key twice (a name repeated in the archive) is deleted once.
        backend.delete_keys(list(dict.fromkeys(keys)))
    except Exception:
        logger.exception("Could not remove {} objects of a failed archive upload", len(keys))


def _upload_members(
    archive_file, guard, backend, folder_key, part_size, workers, started: list[str]
) -> dict[str, int]:
    """upload_archive_members without the cleanup; appends each key to `started`
    before writing it, so a failure knows what to take back."""
    written: dict[str, int] = {}
    pending: dict[str, Future] = {}

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="archive-put") as pool:
        try:
            for name, reader in backend.iter_archive_members_streaming(archive_file, guard):
                key = f"{folder_key}/{name}"
                if name in pending:
                    # The same name twice in one archive: the later file must win.
                    pending.pop(name).result()

                head = _read_at_most(reader, part_size + 1)
                if len(head) <= part_size:
                    _wait_for_free_worker(pending, workers)
                    started.append(key)
                    pending[name] = pool.submit(backend.put_bytes, key, head)
                    written[name] = len(head)
                else:
                    member = _ReplayingReader(head, reader)
                    started.append(key)
                    backend.upload_stream(key, member, part_size=part_size)
                    written[name] = member.bytes_read

            for future in pending.values():
                future.result()
        except BaseException:
            for future in pending.values():
                future.cancel()
            raise

    return written


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
    """File-like: gives back the bytes already read off a member, then the rest of
    it, counting what it hands out. read(n) returns n bytes until EOF: boto turns
    each read into one part, and a short one mid-upload is rejected by S3."""

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


def _wait_for_free_worker(pending: dict[str, Future], workers: int) -> None:
    """Block until fewer than `workers` uploads are running; re-raise any that failed."""
    while len(pending) >= workers:
        done, _ = wait(pending.values(), return_when=FIRST_COMPLETED)
        for name in [n for n, f in pending.items() if f in done]:
            pending.pop(name).result()
