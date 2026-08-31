import json
from types import CoroutineType
import uuid
from typing import Any
from dataclasses import asdict, dataclass
import asyncio

from loguru import logger
from dotdict import DotDict

from services.agent_task_service import AgentTaskService
from services.graph.events import StopEvent
from services.graph.exceptions import StopSession
from services.crew.crew_parser_service import CrewParserService
from services.redis_service import AsyncPubsubSubscriber, RedisService
from services.graph.graph_builder import SessionGraphBuilder
from services.run_python_code_service import RunPythonCodeService
from services.knowledge_search_service import KnowledgeSearchService
from utils.singleton_meta import SingletonMeta
from models.graph_models import GraphMessage
from settings import DEFAULT_TOKEN_BUDGET

from src.shared.models import SessionData, StopSessionMessage
from src.crew.services.graph.shared_variables import (
    SharedVariables,
    SharedVariableScope,
    cleanup_session,
)

# Reserved key smuggled through SessionData.initial_state (a pre-existing
# free-form dict[str, Any] field) to carry an optional per-run token-budget
# override from Django's RunSession request without adding a new typed field
# to the SessionData pydantic contract. Popped out of initial_state before it
# becomes part of the graph's live "variables" state, so it never leaks to
# user-visible flow variables/templates.
TOKEN_BUDGET_STATE_KEY = "__token_budget__"


def _extract_finish_token_total(message_data: dict) -> int:
    """Extract total_tokens from a streamed custom-chunk's message_data, if any.

    Mirrors the extraction logic in
    tables/services/redis_pubsub.py::_calculate_subgraph_token_usage so both
    sides agree on where token usage lives in a "finish" message: CrewNode
    (services/graph/nodes/crew_node.py) embeds it as output["token_usage"].
    Subgraph finish messages are re-streamed through the same parent
    graph.astream() custom-stream (see subgraphs/subgraph_node.py
    _execute_subgraph -> writer(data)), so nested crew nodes' finish
    messages surface here too and are counted the same way.
    """
    if not isinstance(message_data, dict):
        return 0

    output = message_data.get("output")
    token_usage = None
    if isinstance(output, dict) and isinstance(output.get("token_usage"), dict):
        token_usage = output["token_usage"]
    elif isinstance(message_data.get("token_usage"), dict):
        token_usage = message_data["token_usage"]

    if not token_usage:
        return 0

    return token_usage.get("total_tokens", 0) or 0


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
        agent_task_service: AgentTaskService | None = None,
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
            agent_task_service (AgentTaskService | None): The service responsible for delegating TaskNode
                execution to the agent microservice.
        """

        self.redis_service = redis_service
        self.crew_parser_service = crew_parser_service
        self.python_code_executor_service = python_code_executor_service
        self.session_schema_channel = session_schema_channel
        self.session_timeout_channel = session_timeout_channel
        self.crewai_output_channel = crewai_output_channel
        self.stop_session_channel = stop_session_channel
        self.knowledge_search_service = knowledge_search_service
        self.agent_task_service = agent_task_service
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
            # Copy so popping the reserved budget key never mutates the
            # pydantic SessionData model itself.
            initial_state = dict(session_data.initial_state)

            # optional run-level token budget hard stop.
            # Per-run override (if Django threaded one through the request)
            # takes precedence over the global env/settings default. Both
            # default to None ("no limit"), so this is fully inert unless
            # explicitly configured -- byte-for-byte unchanged behavior for
            # existing runs.
            token_budget = initial_state.pop(TOKEN_BUDGET_STATE_KEY, None)
            if token_budget is None:
                token_budget = DEFAULT_TOKEN_BUDGET
            # Local to this call -- NOT stored on `self` -- so concurrent
            # sessions (GraphSessionManagerService is a process-wide
            # singleton) never share or leak a running total.
            token_usage_total = 0

            session_graph_builder = SessionGraphBuilder(
                session_id=session_id,
                redis_service=self.redis_service,
                crew_parser_service=self.crew_parser_service,
                python_code_executor_service=self.python_code_executor_service,
                crewai_output_channel=self.crewai_output_channel,
                knowledge_search_service=self.knowledge_search_service,
                stop_event=stop_event,
                agent_task_service=self.agent_task_service,
            )

            graph = session_graph_builder.compile_from_schema(session_data=session_data)

            shared_vars = SharedVariables(
                session_id=session_id,
                redis_service=self.redis_service,
            )

            state = {
                "state_history": [],
                "variables": DotDict(initial_state),
                "system_variables": {"nodes": {}},
                "execution_counts": {},
            }

            # Add shared variables to state
            state["variables"]["shared"] = shared_vars

            await self.redis_service.aupdate_session_status(
                session_id=session_id,
                status="run",
                variables=state["variables"].model_dump(),
            )
            final_state = state  # Will be updated with last 'values' chunk
            async for stream_mode, chunk in graph.astream(
                input=state,
                config={"recursion_limit": 1000},
                stream_mode=["values", "custom"],
            ):  # TODO: change hardcoded recursion limit
                if stream_mode == "values":
                    final_state = chunk
                elif stream_mode == "custom":
                    # Clean SharedVariable objects from chunk before serialization
                    import dataclasses

                    def deep_clean(obj):
                        if isinstance(obj, (SharedVariables, SharedVariableScope)):
                            return None
                        elif isinstance(obj, dict):
                            cleaned = {}
                            for k, v in obj.items():
                                if k == "shared" and isinstance(
                                    v, (SharedVariables, SharedVariableScope)
                                ):
                                    continue
                                cleaned_v = deep_clean(v)
                                if cleaned_v is not None or not isinstance(
                                    v, (SharedVariables, SharedVariableScope)
                                ):
                                    cleaned[k] = cleaned_v
                            return cleaned
                        elif isinstance(obj, (list, tuple)):
                            return [deep_clean(item) for item in obj]
                        elif dataclasses.is_dataclass(obj) and not isinstance(
                            obj, type
                        ):
                            cleaned_fields = {}
                            for field in dataclasses.fields(obj):
                                value = getattr(obj, field.name)
                                cleaned_fields[field.name] = deep_clean(value)
                            return dataclasses.replace(obj, **cleaned_fields)
                        else:
                            return obj

                    try:
                        cleaned_chunk = deep_clean(chunk)
                        data = asdict(cleaned_chunk)
                    except Exception as e:
                        logger.error(
                            f"Error during chunk cleaning/serialization: {e}",
                            exc_info=True,
                        )
                        data = {
                            "session_id": chunk.session_id
                            if hasattr(chunk, "session_id")
                            else None,
                            "name": chunk.name if hasattr(chunk, "name") else None,
                            "execution_order": chunk.execution_order
                            if hasattr(chunk, "execution_order")
                            else None,
                            "message_data": {"message_type": "error", "error": str(e)},
                        }

                    assert isinstance(data, dict), "custom chunk must be a dict"
                    data["uuid"] = str(uuid.uuid4())

                    if token_budget is not None:
                        token_usage_total += _extract_finish_token_total(
                            data.get("message_data") or {}
                        )
                        if token_usage_total > token_budget:
                            logger.warning(
                                f"Session {session_id} exceeded token budget "
                                f"({token_usage_total} > {token_budget}). "
                                "Stopping session."
                            )
                            stop_event.reason = "token budget exceeded"
                            # Reuse the existing manual-stop status/path
                            # (StopEvent default_status="stop") -- same
                            # mechanism as _handle_stop_session /
                            # _handle_session_timeout, so the abort is
                            # handled by the already-exercised StopSession
                            # flow (nodes' _cleanup_on_stop, EndNode skip,
                            # etc.) with no new status.
                            stop_event.set()

                    self.redis_service.publish("graph:messages", data)
                elif stream_mode == "values":
                    final_state = chunk

                logger.debug(f"Mode: {stream_mode}. Chunk: {chunk}")
                stop_event.check_stop()

            await asyncio.sleep(0.01)

            end_node_result = session_graph_builder.end_node_result

            def _clean_result(obj):
                if isinstance(obj, (SharedVariables, SharedVariableScope)):
                    return None
                elif isinstance(obj, dict):
                    return {
                        k: _clean_result(v)
                        for k, v in obj.items()
                        if not isinstance(v, (SharedVariables, SharedVariableScope))
                    }
                elif isinstance(obj, (list, tuple)):
                    return [_clean_result(i) for i in obj]
                return obj

            end_node_result = _clean_result(end_node_result)
            graph_end_data = GraphMessage(
                session_id=session_id,
                name="",
                execution_order=0,
                message_data={
                    "message_type": "graph_end",
                    "end_node_result": end_node_result,
                    "sse_visible": True,
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

            # Cleanup shared variables
            await cleanup_session(session_id, self.redis_service, status="completed")
            await session_graph_builder.remembered_outputs_store.clear(session_id)

        except asyncio.CancelledError:
            # Status updated in _handle_session_timeout
            logger.warning(f"Session {session_id} was cancelled")
        except StopSession as e:
            status_kwargs = {"reason": e.reason} if e.reason else {}
            await self.redis_service.aupdate_session_status(
                session_id=session_id, status=stop_event.status, **status_kwargs
            )

        except Exception as e:
            logger.exception(f"Failed to start session: {e}")

            await self.redis_service.aupdate_session_status(
                session_id=session_id, status="error", error=f"Unhandled error. \n{e}"
            )

    async def _listen_callback(self, message: dict[str, Any]):
        try:
            channel = message["channel"]
            data = message["data"]
            logger.debug("Get message from {}", channel)

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
