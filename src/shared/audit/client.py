import asyncio
from typing import Generic, Optional

import httpx
from loguru import logger

from src.shared.audit.protocols import T

_DEFAULT_BATCH_SIZE = 200
_DEFAULT_BATCH_INTERVAL_SECONDS = 1.5
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_MAX_QUEUE_SIZE = 10_000
_RETRY_BACKOFFS_SECONDS = (0.2, 0.5, 1.0)


class AuditClient(Generic[T]):
    """
    Async, batching, best-effort client for sending audit-domain events to
    their ingest endpoint. Generic over the event type (SessionAuditEvent
    today; a future UserActionEvent reuses this class unchanged) and
    parameterized by which ingest path it targets - domain-specific
    instantiation, shared mechanics.

    An audit failure must never affect the caller's primary work: emit()
    never raises, and a persistently-failing batch is dropped (logged)
    rather than retried forever.
    """

    def __init__(
        self,
        *,
        base_url: str,
        ingest_path: str,
        api_key: str,
        enabled: bool = True,
        immediate: bool = False,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        batch_interval_seconds: float = _DEFAULT_BATCH_INTERVAL_SECONDS,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        max_queue_size: int = _DEFAULT_MAX_QUEUE_SIZE,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        """
        http_client: inject a pre-built httpx.AsyncClient (e.g. one backed
        by httpx.MockTransport) for testing. Production callers should leave
        this unset - a real client is built automatically.

        immediate: send each event synchronously within its own emit() call
        instead of enqueueing for a background batch loop. Required for
        callers with no persistent event loop (e.g. django_app's HITL call
        site via asgiref.sync.async_to_sync, which spins up a temporary loop
        per call and tears it down right after - a background task started
        there would be abandoned before ever running). __init__ itself must
        stay safe to call with no running loop at all: asyncio.create_task
        requires one, so it's only ever called when NOT immediate, and even
        then only from a caller (crew) that's already inside a persistent
        loop. crew should leave this False (it benefits from real batching
        across many concurrent node events).

        max_queue_size: upper bound on events waiting for the flush loop.
        During an auditor outage the loop stalls in retries while emit()
        keeps enqueueing, so an unbounded queue would grow without limit;
        once full, new events are dropped and counted instead.
        """
        self._url = f"{base_url.rstrip('/')}{ingest_path}"
        self._api_key = api_key
        self._enabled = enabled
        self._immediate = immediate
        self._batch_size = batch_size
        self._batch_interval_seconds = batch_interval_seconds
        self._max_retries = max_retries

        self._queue: "asyncio.Queue[T]" = asyncio.Queue(maxsize=max_queue_size)
        self._dropped_on_full_queue_count = 0
        self._flush_task: Optional[asyncio.Task] = None
        self._http_client: Optional[httpx.AsyncClient] = None

        if self._enabled:
            self._http_client = http_client or httpx.AsyncClient()
            if not self._immediate:
                self._flush_task = asyncio.create_task(self._flush_loop())
                self._flush_task.add_done_callback(self._on_flush_task_done)
        else:
            logger.warning(
                "AuditClient for {} constructed with enabled=False - "
                "every emit() call will silently no-op.",
                self._url,
            )

    async def emit(self, event: T) -> None:
        """Never raises - enqueues for background flush (or sends immediately
        in immediate mode), or no-ops if disabled."""
        if not self._enabled:
            return
        if self._immediate:
            await self._send_batch([event])
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._dropped_on_full_queue_count += 1
            logger.warning(
                "Audit queue for {} is full ({} event(s)), dropping event {}; "
                "{} event(s) dropped on a full queue so far",
                self._url,
                self._queue.maxsize,
                event.id,
                self._dropped_on_full_queue_count,
            )

    def _on_flush_task_done(self, task: asyncio.Task) -> None:
        """
        get_session_audit_writer() is a process-wide lru_cache(maxsize=1)
        singleton - if this task ever dies (cancellation aside), every
        future emit() call for the rest of the process's life silently
        enqueues into a queue nobody drains again: put_nowait() never
        raises, so there is no other signal that audit has gone dark.
        Observed in practice: the loop died mid-session with zero error
        logged anywhere, and every session afterwards produced a complete
        Postgres trace but zero OpenSearch documents. _flush_loop's own
        try/except (below) is the real fix - this callback is the last-
        resort visibility net for any escape it doesn't anticipate.
        """
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "Audit flush loop for {} died unexpectedly - all further "
                "emit() calls will silently no-op for the rest of this "
                "process's life. Error: {!r}",
                self._url,
                exc,
            )

    async def _flush_loop(self) -> None:
        while True:
            try:
                batch = await self._collect_batch()
                if batch:
                    await self._send_batch(batch)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # Never let one bad iteration kill the loop permanently -
                # see _on_flush_task_done's docstring for why that's so much
                # worse here than in a typical background task.
                logger.warning("Audit flush loop iteration failed, continuing: {}", e)

    async def _collect_batch(self) -> list[T]:
        """Batches by size-or-time, whichever hits first."""
        batch: list[T] = [await self._queue.get()]

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._batch_interval_seconds
        while len(batch) < self._batch_size:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                batch.append(
                    await asyncio.wait_for(self._queue.get(), timeout=remaining)
                )
            except asyncio.TimeoutError:
                break

        return batch

    async def _send_batch(self, batch: list[T]) -> None:
        """
        One event failing to serialize (e.g. a stray non-JSON-safe object
        leaking into a field) must not cost the whole batch its unrelated
        events - build the payload item-by-item so a single bad event is
        dropped and logged on its own, not silently taking N good ones
        down with it.
        """
        payload = []
        for event in batch:
            try:
                payload.append(event.model_dump(mode="json"))
            except Exception as e:
                logger.warning(
                    "Dropping unserializable audit event {}: {}", event.id, e
                )
        if not payload:
            return

        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = await self._http_client.post(
                    self._url,
                    json=payload,
                    headers={"X-API-Key": self._api_key},
                    timeout=5.0,
                )
                response.raise_for_status()

                if response.status_code == 207:
                    failed_ids = set(response.json().get("failed_ids", []))
                    payload = [e for e in payload if e.get("id") in failed_ids]
                    if not payload:
                        return
                    if attempt < self._max_retries - 1:
                        logger.warning(
                            "Audit batch to {} partially failed: {} event(s) "
                            "not indexed, retrying: {}",
                            self._url,
                            len(payload),
                            [e.get("id") for e in payload],
                        )
                        await asyncio.sleep(_retry_backoff_seconds(attempt))
                        continue
                    else:
                        event_ids = [e.get("id") for e in payload]
                        logger.warning(
                            "Audit batch to {} still had {} event(s) failing "
                            "after {} attempt(s), dropping: {}",
                            self._url,
                            len(payload),
                            self._max_retries,
                            event_ids,
                        )
                        return

                logger.info(
                    "Audit batch sent to {}: {} event(s), status={}",
                    self._url,
                    len(payload),
                    response.status_code,
                )
                return
            except httpx.HTTPStatusError as e:
                if e.response.status_code < 500:
                    logger.error(
                        "Audit batch to {} rejected with status {}, dropping {} "
                        "event(s) without retry: {}. Response: {}",
                        self._url,
                        e.response.status_code,
                        len(payload),
                        [event.get("id") for event in payload],
                        e.response.text,
                    )
                    return
                last_error = e
            except httpx.TransportError as e:
                last_error = e
            except Exception as e:
                logger.error(
                    "Audit batch to {} failed with a non-retryable error, "
                    "dropping {} event(s): {}. Error: {!r}",
                    self._url,
                    len(payload),
                    [event.get("id") for event in payload],
                    e,
                )
                return

            if attempt < self._max_retries - 1:
                await asyncio.sleep(_retry_backoff_seconds(attempt))
            else:
                logger.warning(
                    "Audit batch send to {} failed after {} attempt(s), "
                    "dropping {} event(s): {}. Error: {}",
                    self._url,
                    self._max_retries,
                    len(payload),
                    [event.get("id") for event in payload],
                    last_error,
                )

    async def shutdown(self) -> None:
        """Best-effort bounded drain-and-flush on graceful process exit."""
        if not self._enabled:
            return

        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        remaining: list[T] = []
        while not self._queue.empty():
            remaining.append(self._queue.get_nowait())

        if remaining:
            try:
                await asyncio.wait_for(self._send_batch(remaining), timeout=5.0)
            except Exception as e:
                logger.warning(
                    "Failed to flush {} audit event(s) on shutdown: {}",
                    len(remaining),
                    e,
                )

        if self._http_client:
            await self._http_client.aclose()


def _retry_backoff_seconds(attempt: int) -> float:
    return _RETRY_BACKOFFS_SECONDS[min(attempt, len(_RETRY_BACKOFFS_SECONDS) - 1)]
