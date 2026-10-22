import asyncio
import signal
import socket
import sys
from collections.abc import Awaitable, Callable
from uuid import uuid4

import settings
from app.data_loader import DataLoader
from app.enums import RunType
from app.factory import RunnerFactory
from app.llm.config import configure_litellm
from app.llm.litellm_client import LiteLLMClient
from app.loop.agent_loop import DefaultAgentLoop
from app.request_handler import RequestHandler
from app.resources.resolver import AgentResolver
from app.runners.deps import RunnerDependencies
from app.runners.list_of_tasks import ListOfTasksRunner
from app.runners.single_task import SingleTaskRunner
from app.sandbox.client import SandboxClient
from app.tools.mcp.client_factory import FastMCPClientFactory
from app.tools.mcp.gateway import McpToolGateway
from loguru import logger
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from shared.bench_log import add_bench_sink, without_bench
from shared.knowledge.client import KnowledgeClient
from shared.redis_streams import RedisStreamClient, StreamEnvelope, StreamMessage


async def _ensure_request_group(client: RedisStreamClient) -> None:
    await client.ensure_group(
        stream=settings.AGENT_REQUEST_STREAM,
        group=settings.AGENT_CONSUMER_GROUP,
        start_id="0",
        mkstream=True,
    )


async def _read_requests(
    client: RedisStreamClient, consumer_name: str, count: int
) -> list[StreamMessage]:
    try:
        return await client.read(
            streams={settings.AGENT_REQUEST_STREAM: ">"},
            group=settings.AGENT_CONSUMER_GROUP,
            consumer=consumer_name,
            count=count,
            block_ms=5000,
        )
    except ResponseError as error:
        # Redis lost the group (restart without persistence, FLUSHALL); redis-py
        # never retries a ResponseError, so recreate the group here.
        if "NOGROUP" not in str(error):
            raise
        logger.warning("consumer group missing, recreating it: {}", error)
        await _ensure_request_group(client)
        return []


async def _process_message(
    client: RedisStreamClient, handler: RequestHandler, message: StreamMessage
) -> None:
    # Runs as a background task nobody awaits: an exception escaping it would only
    # surface as asyncio's "Task exception was never retrieved", outside loguru.
    try:
        try:
            envelope = StreamEnvelope.from_fields(message.fields)

        except Exception as parse_error:
            logger.error(
                "failed to parse message message_id={} error={} — dropping (poison pill)",
                message.message_id,
                parse_error,
            )
            await client.ack(
                settings.AGENT_REQUEST_STREAM,
                settings.AGENT_CONSUMER_GROUP,
                message.message_id,
            )
            return

        # create_task copied the context, so this tag stays on this run's log lines.
        with logger.contextualize(correlation_id=envelope.correlation_id):
            await handler.handle(
                envelope=envelope,
                message_id=message.message_id,
                stream=message.stream,
            )

    except Exception:
        logger.exception("failed to process message_id={}", message.message_id)


async def consume_requests(
    client: RedisStreamClient,
    handler: RequestHandler,
    consumer_name: str,
    max_concurrent_runs: int,
    stop: asyncio.Event,
    *,
    read_retry_initial_delay_s: float,
    read_retry_max_delay_s: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Handle request-stream messages concurrently until ``stop`` is set.

    Reads only as many messages as there are free run slots, so messages this
    replica cannot start yet stay unclaimed in the stream for other replicas
    instead of waiting in this consumer's pending list. A connection or timeout
    error is logged and retried with a doubling delay capped at
    ``read_retry_max_delay_s``, so a Redis outage never ends the process; any
    other Redis error is permanent and propagates. On stop or cancellation, finishes only
    after every in-flight run has finished, so no run is cancelled before
    publishing its result.
    """
    in_flight: set[asyncio.Task] = set()
    read_retry_delay_s = read_retry_initial_delay_s

    try:
        while not stop.is_set():
            free_slots = max_concurrent_runs - len(in_flight)

            if free_slots == 0:
                await asyncio.wait(in_flight, return_when=asyncio.FIRST_COMPLETED)
                continue

            try:
                messages = await _read_requests(client, consumer_name, free_slots)
            except (RedisConnectionError, RedisTimeoutError):
                logger.exception(
                    "reading the request stream failed, retrying in {} s", read_retry_delay_s
                )
                await sleep(read_retry_delay_s)
                read_retry_delay_s = min(read_retry_delay_s * 2, read_retry_max_delay_s)
                continue
            read_retry_delay_s = read_retry_initial_delay_s

            for message in messages:
                task = asyncio.create_task(_process_message(client, handler, message))
                in_flight.add(task)
                task.add_done_callback(in_flight.discard)

    finally:
        await asyncio.gather(*in_flight, return_exceptions=True)


async def main() -> None:
    configure_litellm(settings.AGENT_DROP_UNSUPPORTED_LLM_PARAMS)

    logger.remove()
    logger.configure(extra={"correlation_id": "-"})
    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        filter=without_bench(),
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | "
            "{extra[correlation_id]} | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        backtrace=True,
        diagnose=False,
    )
    add_bench_sink(sys.stderr, settings.LOG_LEVEL)

    consumer_name = f"{socket.gethostname()}-{uuid4().hex[:8]}"

    client = RedisStreamClient(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
    )
    await client.connect()
    await _ensure_request_group(client)

    sandbox_client = SandboxClient(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
        result_channel=settings.CODE_RESULT_CHANNEL,
        sandbox_base_url=f"http://{settings.SANDBOX_HOST}:{settings.SANDBOX_PORT}",
        sandbox_timeout=settings.AGENT_SANDBOX_TIMEOUT,
    )
    await sandbox_client.start()

    knowledge_client = KnowledgeClient(base_url=settings.KNOWLEDGE_BASE_URL)
    await knowledge_client.start()

    loader = DataLoader(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
    )
    await loader.connect()

    llm = LiteLLMClient()
    mcp_gateway = McpToolGateway(
        FastMCPClientFactory(), describe_cache_ttl_s=settings.AGENT_MCP_DESCRIBE_CACHE_TTL
    )
    deps = RunnerDependencies(
        resolver=AgentResolver(sandbox_client, mcp_gateway, knowledge_client),
        loop=DefaultAgentLoop(llm, settings.AGENT_CONTEXT_WARNING_RATIO),
    )
    factory = RunnerFactory(deps)
    factory.register(RunType.SINGLE_TASK, SingleTaskRunner)
    factory.register(RunType.LIST_OF_TASKS, ListOfTasksRunner)

    handler = RequestHandler(
        loader=loader,
        factory=factory,
        redis_client=client,
        result_stream_prefix=settings.AGENT_RESULT_STREAM,
        result_stream_ttl_s=settings.AGENT_RESULT_STREAM_TTL,
        request_stream=settings.AGENT_REQUEST_STREAM,
        consumer_group=settings.AGENT_CONSUMER_GROUP,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _on_signal() -> None:
        logger.info("shutdown signal received")
        stop.set()

    try:
        loop.add_signal_handler(signal.SIGTERM, _on_signal)
        loop.add_signal_handler(signal.SIGINT, _on_signal)
    except NotImplementedError:
        pass

    logger.info(
        "waiting for messages (consumer={}, max_concurrent_runs={})",
        consumer_name,
        settings.AGENT_MAX_CONCURRENT_RUNS,
    )

    await consume_requests(
        client,
        handler,
        consumer_name,
        settings.AGENT_MAX_CONCURRENT_RUNS,
        stop,
        read_retry_initial_delay_s=settings.AGENT_REDIS_READ_RETRY_INITIAL_DELAY,
        read_retry_max_delay_s=settings.AGENT_REDIS_READ_RETRY_MAX_DELAY,
    )

    await loader.close()
    await client.close()
    await sandbox_client.stop()
    await knowledge_client.stop()
    logger.info("agent shut down cleanly")


if __name__ == "__main__":
    asyncio.run(main())
