import asyncio
import os
import sys
from dotenv import load_dotenv, find_dotenv

from services.agent_task_service import AgentTaskService
from services.graph.graph_session_manager_service import GraphSessionManagerService
from services.run_python_code_service import RunPythonCodeService
from services.knowledge_search_service import KnowledgeSearchService
from services.redis_service import RedisService
from utils.logger import logger

if "--debug" in sys.argv:
    logger.info("RUNNING IN DEBUG MODE")
    load_dotenv(find_dotenv(".debug.env"), override=True)
else:
    load_dotenv(find_dotenv(".env"))


async def main():
    # Load configuration from environment variables
    redis_host = os.environ.get("REDIS_HOST", "127.0.0.1")
    redis_port = int(os.environ.get("REDIS_PORT", 6379))
    redis_password = os.environ.get("REDIS_PASSWORD")
    session_schema_channel = os.environ.get("SESSION_SCHEMA_CHANNEL", "sessions:schema")
    session_timeout_channel = os.environ.get(
        "SESSION_TIMEOUT_CHANNEL", "sessions:timeout"
    )
    stop_session_channel = os.getenv("STOP_SESSION_CHANNEL", "sessions:stop")
    MAX_CONCURRENT_SESSIONS = int(os.getenv("MAX_CONCURRENT_SESSIONS", "20"))
    agent_request_stream = os.environ.get("AGENT_REQUEST_STREAM", "agent.requests")
    agent_result_stream = os.environ.get("AGENT_RESULT_STREAM", "agent.results")
    agent_result_timeout_s = float(os.environ.get("AGENT_RESULT_TIMEOUT_S", "600"))
    # Initialize services
    redis_service = RedisService(
        host=redis_host, port=redis_port, password=redis_password
    )
    python_code_executor_service = RunPythonCodeService(redis_service=redis_service)
    knowledge_search_service = KnowledgeSearchService(redis_service=redis_service)
    agent_task_service = AgentTaskService(
        redis_service=redis_service,
        request_stream=agent_request_stream,
        result_stream=agent_result_stream,
        default_timeout_s=agent_result_timeout_s,
    )

    session_manager_service = GraphSessionManagerService(
        redis_service=redis_service,
        session_schema_channel=session_schema_channel,
        session_timeout_channel=session_timeout_channel,
        stop_session_channel=stop_session_channel,
        python_code_executor_service=python_code_executor_service,
        # Note:  Used for process human_input
        knowledge_search_service=knowledge_search_service,
        agent_task_service=agent_task_service,
        max_concurrent_sessions=MAX_CONCURRENT_SESSIONS,
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
