import asyncio
import signal
import socket
import sys
from uuid import uuid4

from loguru import logger

from app.data_loader import DataLoader
from app.enums import RunType
from app.factory import RunnerFactory
from app.knowledge.client import KnowledgeClient
from app.llm.config import configure_litellm
from app.llm.litellm_client import LiteLLMClient
from app.loop.agent_loop import DefaultAgentLoop
from app.request_handler import RequestHandler
from app.resources.resolver import AgentResolver
from app.tools.mcp.client_factory import FastMCPClientFactory
from app.tools.mcp.gateway import McpToolGateway
from app.runners.deps import RunnerDependencies
from app.runners.list_of_tasks import ListOfTasksRunner
from app.runners.single_task import SingleTaskRunner
from app.sandbox.client import SandboxClient
import settings
from shared.redis_streams import RedisStreamClient, StreamEnvelope


async def main() -> None:
    configure_litellm(settings.AGENT_DROP_UNSUPPORTED_LLM_PARAMS)

    logger.remove()
    logger.add(sys.stderr, level=settings.LOG_LEVEL, backtrace=True, diagnose=False)

    consumer_name = f"{socket.gethostname()}-{uuid4().hex[:8]}"

    client = RedisStreamClient(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
    )
    await client.connect()
    await client.ensure_group(
        stream=settings.AGENT_REQUEST_STREAM,
        group=settings.AGENT_CONSUMER_GROUP,
        start_id="0",
        mkstream=True,
    )

    sandbox_client = SandboxClient(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
        request_channel=settings.CODE_EXEC_CHANNEL,
        result_channel=settings.CODE_RESULT_CHANNEL,
    )
    await sandbox_client.start()

    knowledge_client = KnowledgeClient(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
        request_channel=settings.KNOWLEDGE_SEARCH_REQUEST_CHANNEL,
        response_channel=settings.KNOWLEDGE_SEARCH_RESPONSE_CHANNEL,
    )
    await knowledge_client.start()

    loader = DataLoader(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
    )
    await loader.connect()

    llm = LiteLLMClient()
    mcp_gateway = McpToolGateway(FastMCPClientFactory())
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
        result_stream=settings.AGENT_RESULT_STREAM,
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

    logger.info("waiting for messages (consumer={})", consumer_name)

    while not stop.is_set():
        messages = await client.read(
            streams={settings.AGENT_REQUEST_STREAM: ">"},
            group=settings.AGENT_CONSUMER_GROUP,
            consumer=consumer_name,
            count=10,
            block_ms=5000,
        )

        for message in messages:
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
                continue

            await handler.handle(
                envelope=envelope,
                message_id=message.message_id,
                stream=message.stream,
            )

    await loader.close()
    await client.close()
    await sandbox_client.stop()
    await knowledge_client.stop()
    logger.info("agent shut down cleanly")


if __name__ == "__main__":
    asyncio.run(main())
