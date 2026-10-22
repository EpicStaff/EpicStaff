import asyncio
import json
import time
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import anyio
from common.utils import client_network
from domain.enums import Stream
from domain.errors import RateLimitedError
from litestar.response import ServerSentEventMessage
from loguru import logger

from application.ports import AbstractFanout, AbstractRateLimiter, AbstractUnitOfWork

SENT_SEQ_LIMIT = 5000
# seq is taken at insert, not commit: re-read this far below the highest seq sent to catch late commits.
REPLAY_WINDOW = 100
# Concurrent streams: per conversation (one visitor token's devices), per client IP, per operator.
STREAMS_PER_CONVERSATION = 5
STREAMS_PER_IP = 50
STREAMS_PER_USER = 5
STREAM_SLOT_RETRY_SECONDS = 15
# A slot lease outlives this many ping intervals; a background task renews it every interval, so only a dead process lets it lapse.
SLOT_LEASE_PINGS = 3


@dataclass
class _Held:
    """The slot keys one stream holds, all leased under the same holder id."""

    holder: str
    keys: list[str] = field(default_factory=list)


class StreamOrchestrator:
    """Follow the event table, using the Redis channel only as a wake-up.

    The subscription is opened before the first read so no wake-up is missed. With a
    `Last-Event-ID` the rows after it are replayed (after `reset` when the cursor is older than
    the oldest stored row); without one the stream starts from now. Either way a `ready` event
    carrying the current seq follows the replay, so a client that saw nothing else still reconnects
    with a cursor. Every wake-up and every idle
    tick re-reads the last `REPLAY_WINDOW` seqs and sends the rows not sent yet, so a lost publish
    or a late commit still arrives.
    """

    def __init__(
        self,
        uow_factory: Callable[[], AbstractUnitOfWork],
        *,
        fanout: AbstractFanout,
        limiter: AbstractRateLimiter,
        ping_seconds: float,
        max_seconds: float,
    ):
        self._uow = uow_factory
        self._fanout = fanout
        self._limiter = limiter
        self._ping = ping_seconds
        self._max = max_seconds
        self._lease = max(1, round(SLOT_LEASE_PINGS * ping_seconds))

    async def conversation_stream(
        self, conversation_id: UUID, last_event_id: int | None, client_ip: str
    ) -> AsyncGenerator[ServerSentEventMessage, None]:
        """Raises RateLimitedError when the conversation or the IP already has its streams open."""
        held = await self._acquire(
            (f"chat:streams:conv:{conversation_id}", STREAMS_PER_CONVERSATION),
            (f"chat:streams:ip:{client_network(client_ip)}", STREAMS_PER_IP),
        )
        return self._stream(
            Stream.CONVERSATION,
            f"chat:conversation:{conversation_id}",
            last_event_id,
            held,
            conversation_id=conversation_id,
        )

    async def inbox_stream(
        self, org_id: int, user_id: int, last_event_id: int | None
    ) -> AsyncGenerator[ServerSentEventMessage, None]:
        """Raises RateLimitedError when the operator already has their streams open."""
        held = await self._acquire((f"chat:streams:user:{user_id}", STREAMS_PER_USER))
        return self._stream(Stream.INBOX, f"chat:org:{org_id}", last_event_id, held, org_id=org_id)

    async def _acquire(self, *slots: tuple[str, int]) -> _Held:
        held = _Held(uuid4().hex)
        for key, limit in slots:
            if not await self._limiter.acquire_slot(key, limit, held.holder, self._lease):
                await self._release(held)
                raise RateLimitedError(STREAM_SLOT_RETRY_SECONDS)
            held.keys.append(key)
        return held

    async def _keep_renewed(self, held: _Held, deadline: float) -> None:
        # Independent of the generator: a client that never reads parks it on `yield`, and must not lose the slot for it.
        # Bounded by the stream deadline, so a stream parked (or never closed) past its lifetime stops holding the slot.
        while time.monotonic() < deadline:
            await asyncio.sleep(self._ping)
            # The loop outlives a Redis blip; the lease covers the missed renewal.
            try:
                for key in held.keys:
                    await self._limiter.renew_slot(key, held.holder, self._lease)
            except Exception as error:
                logger.warning("Stream slot renewal failed: {}", error)

    async def _release(self, held: _Held, renewal: asyncio.Task | None = None) -> None:
        # Shielded: a client disconnect cancels the stream, and the slot must still come back.
        with anyio.CancelScope(shield=True):
            if renewal is not None:
                renewal.cancel()
                # Wait it out so no renewal lands after the release; gather swallows its CancelledError.
                await asyncio.gather(renewal, return_exceptions=True)
            for key in held.keys:
                await self._limiter.release_slot(key, held.holder)

    async def _stream(
        self, stream: Stream, channel: str, last_event_id: int | None, held: _Held, **scope
    ) -> AsyncGenerator[ServerSentEventMessage, None]:
        # Started on the first read, not in `_acquire`: a generator never iterated never runs its finally, so a task
        # started earlier would renew forever, while its lease lapses on its own.
        deadline = time.monotonic() + self._max
        renewal = asyncio.create_task(self._keep_renewed(held, deadline))
        try:
            async with self._fanout.listen(channel, idle_seconds=self._ping) as live:
                async with self._uow() as uow:
                    reset = False
                    if last_event_id is None:
                        high_seq = await uow.events.max_seq(stream, **scope)
                    else:
                        # Seqs are table-wide, so a scope's rows have gaps: the cursor is stale only when
                        # the row it names is gone (retention), i.e. it sits below the oldest surviving one.
                        oldest = await uow.events.min_seq(stream, **scope)
                        reset = 0 < last_event_id < oldest
                        high_seq = 0 if reset else last_event_id
                    rows = await uow.events.replay(
                        stream, after_seq=max(0, high_seq - REPLAY_WINDOW), **scope
                    )
                    head = await uow.events.max_seq(stream, **scope) if reset else 0
                # The client already has what is at or below the start; the window re-reads must not resend it.
                sent = {row.seq for row in rows if row.seq <= high_seq}
                # After a reset the replay is sent in full; `ready` then names the table head, never 0.
                high_seq = max(high_seq, head)
                if reset:
                    yield ServerSentEventMessage(event="reset", data="{}")
                # The Redis payload is ignored: a wake-up, or an idle tick (None), only says "read again".
                wake_up, ready = True, False
                while True:
                    for row in rows:
                        if row.seq not in sent:
                            yield ServerSentEventMessage(
                                id=row.seq, event=row.type, data=json.dumps(row.payload)
                            )
                            sent.add(row.seq)
                            high_seq = max(high_seq, row.seq)
                    if not ready:
                        yield ServerSentEventMessage(id=high_seq, event="ready", data="{}")
                        ready = True
                    if len(sent) > SENT_SEQ_LIMIT:
                        sent = set(sorted(sent)[-SENT_SEQ_LIMIT // 2 :])
                    if wake_up is None:
                        yield ServerSentEventMessage(comment="ping")
                    wake_up = await anext(live)
                    if time.monotonic() > deadline:
                        return
                    async with self._uow() as uow:
                        rows = await uow.events.replay(
                            stream, after_seq=max(0, high_seq - REPLAY_WINDOW), **scope
                        )
        finally:
            await self._release(held, renewal)
