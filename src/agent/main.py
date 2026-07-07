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
from settings import load_settings
from shared.redis_streams import RedisStreamClient, StreamEnvelope


async def main() -> None:
    settings = load_settings()
    configure_litellm(settings.agent_drop_unsupported_llm_params)

    logger.remove()
    logger.add(sys.stderr, level=settings.log_level, backtrace=True, diagnose=False)

    consumer_name = f"{socket.gethostname()}-{uuid4().hex[:8]}"

    client = RedisStreamClient(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
    )
    await client.connect()
    await client.ensure_group(
        stream=settings.agent_request_stream,
        group=settings.agent_consumer_group,
        start_id="0",
        mkstream=True,
    )

    sandbox_client = SandboxClient(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
        request_channel=settings.sandbox_request_channel,
        result_channel=settings.sandbox_result_channel,
    )
    await sandbox_client.start()

    knowledge_client = KnowledgeClient(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
        request_channel=settings.knowledge_search_request_channel,
        response_channel=settings.knowledge_search_response_channel,
    )
    await knowledge_client.start()

    loader = DataLoader(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
    )
    await loader.connect()

    llm = LiteLLMClient()
    mcp_gateway = McpToolGateway(FastMCPClientFactory())
    deps = RunnerDependencies(
        resolver=AgentResolver(sandbox_client, mcp_gateway, knowledge_client),
        loop=DefaultAgentLoop(llm, settings.agent_context_warning_ratio),
    )
    factory = RunnerFactory(deps)
    factory.register(RunType.SINGLE_TASK, SingleTaskRunner)
    factory.register(RunType.LIST_OF_TASKS, ListOfTasksRunner)

    handler = RequestHandler(
        loader=loader,
        factory=factory,
        redis_client=client,
        result_stream=settings.agent_result_stream,
        request_stream=settings.agent_request_stream,
        consumer_group=settings.agent_consumer_group,
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
            streams={settings.agent_request_stream: ">"},
            group=settings.agent_consumer_group,
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
                    settings.agent_request_stream,
                    settings.agent_consumer_group,
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
