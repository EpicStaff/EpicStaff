import json
import uuid
from typing import Any
from dotdict import DotDict
from services.graph.graph_builder import SessionGraphBuilder, State
from services.python_code_executor_service import RunPythonCodeService
from utils.singleton_meta import SingletonMeta
from services.crew.crew_parser_service import CrewParserService
from services.redis_service import RedisService
from models.request_models import GraphSessionMessageData, SessionData
from loguru import logger
import asyncio
from pathlib import Path
from utils.helpers import load_env
from services.graph.graph_builder import SessionGraphBuilder
from services.knowledge_search_service import KnowledgeSearchService
from dataclasses import asdict


class GraphSessionManagerService(metaclass=SingletonMeta):
    def __init__(
        self,
        redis_service: RedisService,
        crew_parser_service: CrewParserService,
        python_code_executor_service: RunPythonCodeService,
        session_schema_channel: str,
        session_timeout_channel: str,
        crewai_output_channel: str,
        knowledge_search_service: KnowledgeSearchService,
    ):
        """
        Initializes the GraphSessionManagerService with the required services and configuration.

        Args:
            redis_service (RedisService): The service responsible for Redis operations.
            crew_parser_service (CrewParserService): The service responsible for parsing crew data.
            python_code_executor_service (RunPythonCodeService): The service responsible for executing Python code.
            session_schema_channel (str): The Redis channel for listening to session schema messages.
            crewai_output_channel (str): The Redis channel for publishing CrewAI output messages.
        """

        self.session_graph_pool: dict[int, asyncio.Task] = {}
        self.redis_service = redis_service
        self.crew_parser_service = crew_parser_service
        self.python_code_executor_service = python_code_executor_service
        self.session_schema_channel = session_schema_channel
        self.session_timeout_channel = session_timeout_channel
        self.crewai_output_channel = crewai_output_channel
        self.knowledge_search_service = knowledge_search_service

    def start(self):
        self._listener_task = asyncio.create_task(self._listen_to_channels())
        logger.info("Session Manager Service is now running.")

    async def run_session(self, session_data: SessionData):

        try:
            session_id = session_data.id
            initial_state = session_data.initial_state

            session_graph_builder = SessionGraphBuilder(
                session_id=session_id,
                redis_service=self.redis_service,
                crew_parser_service=self.crew_parser_service,
                python_code_executor_service=self.python_code_executor_service,
                crewai_output_channel=self.crewai_output_channel,
                knowledge_search_service=self.knowledge_search_service,
            )

            graph = session_graph_builder.compile_from_schema(session_data=session_data)

            state = {
                "state_history": [],
                "variables": DotDict(initial_state),
                "system_variables": {"nodes": {}},
            }

            await self.redis_service.async_update_session_status(
                session_id=session_id, status="run"
            )
            async for stream_mode, chunk in graph.astream(
                state, stream_mode=["values", "custom"]
            ):
                if stream_mode == "custom":
                    data = asdict(chunk)
                    assert isinstance(data, dict), "custom chunk must be a dict"
                    data["uuid"] = str(uuid.uuid4())

                    await self.redis_service.async_publish("graph:messages", data)
                logger.debug(f"Mode: {stream_mode}. Chunk: {chunk}")

            await self.redis_service.async_update_session_status(
                session_id=session_id, status="end"
            )

        except asyncio.CancelledError:
            # Status updated in _handle_session_timeout
            logger.warning(f"Session {session_id} was cancelled")

        except Exception as e:
            logger.exception(f"Failed to start session: {e}")

            await self.redis_service.async_update_session_status(
                session_id=session_id, status="error", error=str(e)
            )

    async def _listen_to_channels(self):
        pubsub = await self.redis_service.async_subscribe(
            [self.session_schema_channel, self.session_timeout_channel]
        )

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":

                    channel = (
                        message["channel"].decode("utf-8")
                        if isinstance(message["channel"], bytes)
                        else message["channel"]
                    )
                    data = (
                        message["data"].decode("utf-8")
                        if isinstance(message["data"], bytes)
                        else message["data"]
                    )
                    logger.info(f"Get message from {channel}: {data}")

                    if channel == self.session_schema_channel:
                        # Update env keys first
                        config_path = (
                            Path("env_config/config.yaml").resolve().as_posix()
                        )
                        load_env(config_path)
                        await self._handle_session_start(data)

                    elif channel == self.session_timeout_channel:
                        await self._handle_session_timeout(data)

                    else:
                        logger.info(f"Unknown channel {channel}")

        except Exception as e:  # asyncio.CancelledError
            ...
            logger.exception("PubSub listener task cancelled.")
        finally:
            await pubsub.unsubscribe(self.session_schema_channel)
            await pubsub.unsubscribe(self.session_timeout_channel)

    async def _handle_session_start(self, data: str):
        try:
            logger.info(
                f"Received message from channel {self.session_schema_channel}: {data}"
            )
            session_schema = json.loads(data)
            session_data = SessionData.model_validate(session_schema)
            session_id = session_data.id

            session_task = asyncio.create_task(self.run_session(session_data))
            self.session_graph_pool[session_data.id] = session_task

            def create_callback(sid):
                def remove_task_from_pool(completed_task):
                    if sid in self.session_graph_pool:
                        self.session_graph_pool.pop(sid)
                        logger.info(f"Task for session {sid} removed from pool")

                return remove_task_from_pool

            # callback to clean up completed tasks
            session_task.add_done_callback(create_callback(session_id))
        except Exception as e:
            logger.exception(f"Error handling session start: {e}")

    async def _handle_session_timeout(self, data: str):
        """
        Handle session timeout message
        """
        logger.info(
            f"Received message from channel {self.session_timeout_channel}: {data}"
        )
        try:
            timeout_data = json.loads(data)
            session_id = timeout_data.get("session_id")
            action = timeout_data.get("action")

            if action == "timeout":
                if session_id in self.session_graph_pool:
                    logger.info(f"Handling timeout for session {session_id}")

                    # Remove task from pool and cancel
                    session_task = self.session_graph_pool.pop(session_id)
                    session_task.cancel()

                    await self.redis_service.async_update_session_status(
                        session_id=session_id, status="expired"
                    )

                    logger.info(
                        f"Session {session_id} cancelled due to timeout. Setted status: expired"
                    )
                else:
                    logger.info(
                        f"Can not fetch task from session_graph_pool for session ID: {session_id}. Setted status: expired"
                    )
                    await self.redis_service.async_update_session_status(
                        session_id=session_id, status="expired"
                    )
            else:
                logger.info(f"Handling timeout for session {session_id}")

        except Exception as e:
            logger.exception(f"Error handling session timeout: {e}")
