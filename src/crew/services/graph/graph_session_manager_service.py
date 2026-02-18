import json
from types import CoroutineType
import uuid
from typing import Any
from dataclasses import asdict, dataclass
import asyncio

from loguru import logger
from dotdict import DotDict

from src.crew.services.graph.events import StopEvent
from src.crew.services.graph.exceptions import StopSession
from src.crew.services.crew.crew_parser_service import CrewParserService
from src.crew.services.redis_service import AsyncPubsubSubscriber, RedisService
from src.crew.services.graph.graph_builder import SessionGraphBuilder
from src.crew.services.run_python_code_service import RunPythonCodeService
from src.crew.services.knowledge_search_service import KnowledgeSearchService

from src.crew.utils.singleton_meta import SingletonMeta

from src.crew.models.request_models import SessionData, StopSessionMessage
from src.crew.models.graph_models import GraphMessage


@dataclass
class SessionCoroItem:
    coro: CoroutineType
    stop_event: StopEvent


class GraphSessionManagerService(metaclass=SingletonMeta):
    def __init__(
        self,
        redis_service: RedisService,
        crew_parser_service: CrewParserService,
        python_code_executor_service: RunPythonCodeService,
        session_schema_channel: str,
        session_timeout_channel: str,
        crewai_output_channel: str,
        stop_session_channel: str,
        knowledge_search_service: KnowledgeSearchService,
        max_concurrent_sessions: int = 20,
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

        self.redis_service = redis_service
        self.crew_parser_service = crew_parser_service
        self.python_code_executor_service = python_code_executor_service
        self.session_schema_channel = session_schema_channel
        self.session_timeout_channel = session_timeout_channel
        self.crewai_output_channel = crewai_output_channel
        self.stop_session_channel = stop_session_channel
        self.knowledge_search_service = knowledge_search_service
        self.session_graph_pool: dict[int, SessionCoroItem] = {}
        self.session_queue = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._semaphore = asyncio.Semaphore(max_concurrent_sessions)
        self.counter = 0

    def start(self):
        self._listener_task = asyncio.create_task(self._listen_to_channels())
        self._worker_task = asyncio.create_task(self._session_worker())
        logger.info("Session Manager Service is now running.")

    async def run_session(self, session_data: SessionData, stop_event: StopEvent):
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
                stop_event=stop_event,
            )

            graph = session_graph_builder.compile_from_schema(session_data=session_data)
            state = {
                "state_history": [],
                "variables": DotDict(initial_state),
                "system_variables": {"nodes": {}},
            }
            await self.redis_service.aupdate_session_status(
                session_id=session_id, status="run"
            )
            async for stream_mode, chunk in graph.astream(
                input=state,
                config={"recursion_limit": 1000},
                stream_mode=["values", "custom"],
            ):  # TODO: change hardcoded recursion limit
                if stream_mode == "custom":
                    data = asdict(chunk)
                    assert isinstance(data, dict), "custom chunk must be a dict"
                    data["uuid"] = str(uuid.uuid4())
                    self.redis_service.publish("graph:messages", data)
                elif stream_mode == "values":
                    final_state = chunk

                logger.debug(f"Mode: {stream_mode}. Chunk: {chunk}")
                stop_event.check_stop()

            await asyncio.sleep(0.01)

            graph_end_data = GraphMessage(
                session_id=session_id,
                name="",
                execution_order=0,
                message_data={
                    "message_type": "graph_end",
                    "end_node_result": session_graph_builder.end_node_result,
                },
            )
            graph_end_message_data = asdict(graph_end_data)
            graph_end_message_data["uuid"] = str(uuid.uuid4())

            self.redis_service.publish("graph:messages", graph_end_message_data)
            await asyncio.sleep(0.05)

            await self.redis_service.aupdate_session_status(
                session_id=session_id,
                status="end",
                variables=final_state["variables"].model_dump(),
            )

        except asyncio.CancelledError:
            # Status updated in _handle_session_timeout
            logger.warning(f"Session {session_id} was cancelled")
        except StopSession:
            await self.redis_service.aupdate_session_status(
                session_id=session_id, status=stop_event.status
            )

        except Exception as e:
            logger.exception(f"Failed to start session: {e}")

            await self.redis_service.aupdate_session_status(
                session_id=session_id, status="error", error=f"Unhandled error. \n{e}"
            )
        finally:
            graph_end_data = GraphMessage(
                session_id=session_id,
                name="",
                execution_order=0,
                message_data={
                    "message_type": "graph_end",
                    "end_node_result": session_graph_builder.end_node_result,
                },
            )
            graph_end_message_data = asdict(graph_end_data)
            graph_end_message_data["uuid"] = str(uuid.uuid4())

            self.redis_service.publish("graph:messages", graph_end_message_data)

    async def _listen_callback(self, message: dict[str, Any]):
        try:
            channel = message["channel"]
            data = message["data"]
            logger.debug(f"Get message from {channel}: {data}")

            if channel == self.session_schema_channel:
                await self._handle_session_start(data)

            elif channel == self.session_timeout_channel:
                await self._handle_session_timeout(data)
            elif channel == self.stop_session_channel:
                await self._handle_stop_session(data)
            else:
                logger.info(f"Unknown channel {channel}")
        except Exception:  # asyncio.CancelledError
            logger.exception("Listener task cancelled.")
        finally:
            pass

    async def _listen_to_channels(self):
        subscriber = AsyncPubsubSubscriber(self._listen_callback)
        await self.redis_service.asubscribe(
            [
                self.session_schema_channel,
                self.session_timeout_channel,
                self.stop_session_channel,
            ],
            subscriber=subscriber,
        )

    async def _handle_session_start(self, data: str):
        try:
            logger.info(f"Received message from channel {self.session_schema_channel}")
            session_data = SessionData.model_validate_json(data)

            stop_event = StopEvent()
            coro = self.session_runner(session_data, stop_event)
            coro_item = SessionCoroItem(coro, stop_event)
            self.session_graph_pool[session_data.id] = coro_item
            await self.session_queue.put(session_data.id)

        except Exception as e:
            logger.exception(f"Error handling session start: {e}")

    async def _handle_session_timeout(self, data: str):
        """
        Handle session timeout message
        """
        logger.info(f"Received message from channel {self.session_timeout_channel}")
        try:
            timeout_data = json.loads(data)
            session_id = timeout_data.get("session_id")
            action = timeout_data.get("action")

            if action == "timeout":
                if session_id in self.session_graph_pool:
                    logger.info(f"Handling timeout for session {session_id}")

                    # Remove task from pool and cancel
                    session_task = self.session_graph_pool.pop(session_id)

                    stop_event = session_task.stop_event
                    stop_event.status = "expired"
                    stop_event.set()

                    await self.redis_service.aupdate_session_status(
                        session_id=session_id, status="expired"
                    )

                    logger.info(
                        f"Session {session_id} cancelled due to timeout. Setted status: expired"
                    )
                else:
                    logger.info(
                        f"Can not fetch task from session_graph_pool for session ID: {session_id}. Setted status: expired"
                    )
                    await self.redis_service.aupdate_session_status(
                        session_id=session_id, status="expired"
                    )
            else:
                logger.info(f"Handling timeout for session {session_id}")

        except Exception as e:
            logger.exception(f"Error handling session timeout: {e}")

    async def _handle_stop_session(self, data: str):
        logger.info(f"Received message from channel {self.stop_session_channel}")

        stop_session_message = StopSessionMessage.model_validate(json.loads(data))
        session_id = stop_session_message.session_id
        await self.redis_service.aupdate_session_status(
            session_id=session_id, status="stop"
        )

        if session_id not in self.session_graph_pool:
            logger.warning(
                f"Can not fetch task from session_graph_pool for session ID: {session_id}."
            )
            return
        self.session_graph_pool[session_id].stop_event.set()
        self.session_graph_pool.pop(session_id, None)

    async def session_runner(self, data: SessionData, stop_event: StopEvent):
        async with self._semaphore:
            logger.info(f"Acquired semaphore for session {data.id}")
            await self.run_session(data, stop_event)
            self.counter += 1
            logger.debug(f"Tasks executed: {self.counter}")

    def create_callback(self, sid):
        def remove_task_from_pool(completed_task):
            if sid not in self.session_graph_pool:
                logger.warning(f"Task for session {sid} is not in pool")
                return

            self.session_graph_pool.pop(sid)
            logger.info(f"Task for session {sid} removed from pool")

        return remove_task_from_pool

    async def _session_worker(self):
        logger.info("Session worker started")
        while True:
            session_id: int = await self.session_queue.get()
            session_coro_item: SessionCoroItem = self.session_graph_pool.get(session_id)
            if session_coro_item is None:
                logger.warning(f"Session {session_id} was removed before it started")
                continue

            logger.info(f"Dequeued session {session_id}")

            task = asyncio.create_task(session_coro_item.coro)

            task.add_done_callback(self.create_callback(session_id))
            self.session_queue.task_done()
