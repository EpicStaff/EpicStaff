import asyncio

import settings
from services.agent_task_service import AgentTaskService
from services.crew.mcp_tool_factory import CrewaiMcpToolFactory
from services.graph.graph_session_manager_service import GraphSessionManagerService
from services.run_python_code_service import RunPythonCodeService
from services.crew.crew_parser_service import CrewParserService
from services.knowledge_search_service import KnowledgeSearchService
from services.redis_service import RedisService
from utils.logger import logger


async def main():
    # Initialize services
    redis_service = RedisService(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        user=settings.REDIS_USER,
        password=settings.REDIS_PASSWORD
    )
    python_code_executor_service = RunPythonCodeService(redis_service=redis_service)
    knowledge_search_service = KnowledgeSearchService(redis_service=redis_service)
    agent_task_service = AgentTaskService(
        redis_service=redis_service,
        request_stream=settings.AGENT_REQUEST_STREAM,
        result_stream=settings.AGENT_RESULT_STREAM,
        default_timeout=settings.AGENT_RESULT_TIMEOUT,
    )
    mcp_tool_factory = CrewaiMcpToolFactory()
    crew_parser_service = CrewParserService(
        redis_service=redis_service,
        python_code_executor_service=python_code_executor_service,
        mcp_tool_factory=mcp_tool_factory,
    )
    session_manager_service = GraphSessionManagerService(
        redis_service=redis_service,
        crew_parser_service=crew_parser_service,
        session_schema_channel=settings.SESSION_SCHEMA_CHANNEL,
        session_timeout_channel=settings.SESSION_TIMEOUT_CHANNEL,
        stop_session_channel=settings.STOP_SESSION_CHANNEL,
        python_code_executor_service=python_code_executor_service,
        crewai_output_channel=settings.CREWAI_OUTPUT_CHANNEL,
        # Note:  Used for process human_input
        knowledge_search_service=knowledge_search_service,
        agent_task_service=agent_task_service,
        max_concurrent_sessions=settings.MAX_CONCURRENT_SESSIONS,
    )

    try:
        # Initialize Redis and start listening
        logger.info("Initializing Redis connection...")
        await redis_service.connect()
        logger.info("Redis connection established.")

        logger.info("Starting Session Manager Service...")
        session_manager_service.start()
        logger.info("Session Manager Service started.")
        # Run indefinitely
        # monitor = MemoryMonitor()
        while True:
            await asyncio.sleep(1)
            # monitor.log_memory_usage()

    except Exception as e:
        logger.error(f"An error occurred: {e}", exc_info=True)
    finally:
        logger.info("Shutting down...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down due to keyboard interrupt.")
