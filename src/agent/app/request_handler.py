"""
Layer 6 — RequestHandler: top-level pipeline that drives a single stream message
to completion.

Orchestrates the full request lifecycle: envelope → ``DataLoader`` → ``RunnerFactory``
→ ``Runner.execute`` → ack.  The runner owns the full emitter lifecycle
(on_start → on_final | on_error).  The fallback emitter here only covers
pre-runner failures (load / build).  The message is always acked in finally.
"""

from __future__ import annotations

from loguru import logger

from app.data_loader import DataLoader
from app.emitters.redis_batch import RedisStreamBatchEmitter
from app.factory import RunnerFactory
from shared.redis_streams import RedisStreamClient, StreamEnvelope


class RequestHandler:
    """Consumes a ``StreamEnvelope`` and drives it through the full execution pipeline.

    Collaborators:
    - ``DataLoader`` — hydrates the envelope into an ``AgentRequest``.
    - ``RunnerFactory`` — selects and constructs the ``(Runner, Emitter)`` pair.
    - ``Runner`` — executes the agent work and owns the full emitter lifecycle.
    - ``RedisStreamClient`` — used to ack the message and, via the emitter, to
      publish results.

    The fallback ``RedisStreamBatchEmitter`` is used only for pre-emitter
    failures (load / build).  Once a runner + emitter are built, the runner
    owns on_start → on_final | on_error exclusively.  The stream message is
    acked unconditionally in the finally block.
    """

    def __init__(
        self,
        loader: DataLoader,
        factory: RunnerFactory,
        redis_client: RedisStreamClient,
        result_stream: str,
        request_stream: str,
        consumer_group: str,
    ) -> None:
        self._loader = loader
        self._factory = factory
        self._redis_client = redis_client
        self._result_stream = result_stream
        self._request_stream = request_stream
        self._consumer_group = consumer_group

    async def handle(
        self,
        envelope: StreamEnvelope,
        message_id: str,
        stream: str,
    ) -> None:
        """Process one stream message end-to-end and ack it.

        Runs the pipeline: load → build → execute.  Pre-emitter failures
        (load / build) are caught here and published via a fallback emitter.
        Once a runner is built its ``execute`` owns the emitter lifecycle.
        The message is acked unconditionally.

        Args:
            envelope: parsed stream message payload.
            message_id: Redis stream message ID used for acking.
            stream: name of the stream the message was read from.
        """
        correlation_id = envelope.correlation_id
        logger.info(
            "handling request type={} correlation_id={}",
            envelope.type,
            correlation_id,
        )
        logger.debug(
            "envelope payload correlation_id={} payload={}",
            correlation_id,
            envelope.payload,
        )

        try:
            request = await self._loader.load(envelope)
            runner, emitter = self._factory.build(
                request, self._redis_client, self._result_stream
            )

        except Exception as error:
            logger.exception(
                "request failed before emitter correlation_id={}",
                correlation_id,
            )
            fallback_emitter = RedisStreamBatchEmitter(
                self._redis_client, self._result_stream, correlation_id
            )
            await fallback_emitter.on_error(error)

        else:
            await runner.execute(request, emitter)

        finally:
            await self._redis_client.ack(stream, self._consumer_group, message_id)
            logger.debug(
                "acked message_id={} correlation_id={}", message_id, correlation_id
            )
