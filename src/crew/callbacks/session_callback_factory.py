import json
import os
import time
from typing import Callable, Optional, Union
from crewai.agents.crew_agent_executor import KNOWLEDGE_KEYWORD

from models.graph_models import (
    GraphMessage,
    AgentMessageData,
    AgentFinishMessageData,
    TaskMessageData,
    UpdateSessionStatusMessageData,
)
from services.redis_service import RedisService
from services.knowledge_search_service import KnowledgeSearchService
from datetime import datetime
from crewai.agents.parser import AgentAction, AgentFinish
from crewai.task import TaskOutput
from langgraph.types import StreamWriter

import asyncio
from loguru import logger


SESSION_STATUS_CHANNEL = os.environ.get(
    "SESSION_STATUS_CHANNEL", "sessions:session_status"
)


class GraphSessionCallbackFactory:

    def __init__(
        self, session_id: int, redis_service: RedisService, crewai_output_channel: str
    ):
        self.crewai_output_channel = crewai_output_channel
        self.session_id = session_id
        self.redis_service = redis_service

    def get_done_callback(self) -> Callable[[asyncio.Task], None]:
        """
        Callback to handle the completion of a session task.
        """

        def inner(task: asyncio.Task) -> None:
            try:
                if task.cancelled():
                    logger.warning(f"Session {self.session_id} was cancelled.")
                    self.redis_service.sync_publish(
                        SESSION_STATUS_CHANNEL,
                        {"session_id": self.session_id, "status": "cancelled"},
                    )
                elif task.exception():
                    # Here we go again....
                    exc = task.exception()
                    logger.error(
                        f"Session {self.session_id} task completed with exception"
                    )

                    self.redis_service.sync_publish(
                        SESSION_STATUS_CHANNEL,
                        {
                            "session_id": self.session_id,
                            "status": "error",
                            "error": str(exc),
                        },
                    )
                    raise exc
                else:
                    logger.info(f"Session {self.session_id} finished successfully.")
                    finish_state: dict = task.result()

                    assert isinstance(finish_state, dict)
                    state_history: list = finish_state["state_history"]

                    last_state = state_history[-1]

                    self.redis_service.sync_publish(
                        SESSION_STATUS_CHANNEL,
                        {
                            "session_id": self.session_id,
                            "status": "end",
                            "status_data": {
                                "state_history": state_history,
                                "output": last_state["output"],
                            },
                        },
                    )
            except Exception as e:
                logger.exception(
                    f"Error in done callback for session {self.session_id}: {e}"
                )

        return inner


class CrewCallbackFactory:
    def __init__(
        self,
        session_id: int,
        node_name: str,
        crew_id: int,
        execution_order: int,
        redis_service: RedisService,
        knowledge_search_service: KnowledgeSearchService,
        crewai_output_channel: str,
        stream_writer: Optional[StreamWriter] = None,
    ):
        self.redis_service = redis_service
        self.crewai_output_channel = crewai_output_channel
        self.session_id = session_id
        self.node_name = node_name
        self.crew_id = crew_id
        self.execution_order = execution_order
        self.stream_writer = stream_writer
        self.knowledge_search_service = knowledge_search_service

    def get_step_callback(
        self, agent_id: int
    ) -> Callable[[Union[AgentAction, AgentFinish]], None]:
        def inner(output: AgentAction | AgentFinish) -> None:

            if isinstance(output, AgentAction):
                self._publish_agent_action(
                    agent_id=agent_id,
                    agent_action=output,
                )
            elif isinstance(output, AgentFinish):
                self._publish_agent_finish(
                    agent_id=agent_id,
                    agent_finish=output,
                )
            else:
                raise ValueError("Invalid output class type")

        return inner

    def _publish_agent_finish(
        self,
        agent_id: int,
        agent_finish: AgentFinish,
    ) -> None:
        try:
            logger.info(
                f"_publish_agent_finish crew {self.crew_id} "
                f"execution_order {self.execution_order} "
                f"node_name {self.node_name} "
                f"agent {agent_id} session {self.session_id}:\n"
                f"Thought: {agent_finish.thought}\n"
                f"Output: {agent_finish.output}\n"
                f"Text: {agent_finish.text}\n"
            )

            agent_finish_message_data = AgentFinishMessageData(
                crew_id=self.crew_id,
                agent_id=agent_id,
                thought=agent_finish.thought,
                text=agent_finish.text,
                output=agent_finish.output,
            )
            graph_message = GraphMessage(
                session_id=self.session_id,
                name=self.node_name,
                execution_order=self.execution_order,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                message_data=agent_finish_message_data,
            )

            if self.stream_writer is not None:
                self.stream_writer(graph_message)

        except Exception as e:
            logger.error(f"Error in step callback for session {self.session_id}: {e}")

    def _publish_agent_action(
        self,
        agent_id: int,
        agent_action: AgentAction,
    ) -> None:
        try:
            logger.info(
                f"Step callback for crew {self.crew_id}"
                f"agent {agent_id} session {self.session_id} execution_order {self.execution_order}:\n"
                f"Thought: {agent_action.thought}\n"
                f"Tool: {agent_action.tool}\n"
                f"Input: {agent_action.tool_input}\n"
                f"Text: {agent_action.text}\n"
                f"Result: {agent_action.result}"
            )
            agent_message_data = AgentMessageData(
                crew_id=self.crew_id,
                agent_id=agent_id,
                thought=agent_action.thought,
                tool=agent_action.tool,
                tool_input=agent_action.tool_input,
                text=agent_action.text,
                result=agent_action.result,
            )
            graph_message = GraphMessage(
                session_id=self.session_id,
                name=self.node_name,
                execution_order=self.execution_order,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                message_data=agent_message_data,
            )

            if self.stream_writer is not None:
                self.stream_writer(graph_message)

        except Exception as e:
            logger.error(f"Error in step callback for session {self.session_id}: {e}")

    def get_task_callback(self, task_id: int) -> Callable[[TaskOutput], None]:
        def inner(output: TaskOutput) -> None:
            try:
                logger.info(
                    f"Task callback for crew {self.crew_id} "
                    f"session {self.session_id} execution_order {self.execution_order}: {output.raw}"
                )

                task_message_data = TaskMessageData(
                    crew_id=self.crew_id,
                    task_id=task_id,
                    description=output.description,
                    raw=output.raw,
                    name=output.name,
                    expected_output=output.expected_output,
                    agent=output.agent,
                )
                graph_message = GraphMessage(
                    session_id=self.session_id,
                    name=self.node_name,
                    execution_order=self.execution_order,
                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    message_data=task_message_data,
                )

                if self.stream_writer is not None:
                    self.stream_writer(graph_message)

            except Exception as e:
                logger.error(f"Error in task callback: {e}")

        return inner

    def _extract_knowledges(self, knowledge_snippets: list) -> str:
        snippet = "\n\n".join(knowledge_snippets)
        return f'{KNOWLEDGE_KEYWORD} \n\n"{snippet}"' if knowledge_snippets else ""

    def get_wait_for_user_callback(
        self,
        crew_knowledge_collection_id=None,
        agent_knowledge_collection_id=None,
    ) -> Callable[[], str]:
        def inner() -> str:
            update_session_status_message_data = UpdateSessionStatusMessageData(
                crew_id=self.crew_id,
                status="wait_for_user",
                status_data={
                    "name": self.node_name,
                    "execution_order": self.execution_order,
                },
            )
            graph_message = GraphMessage(
                session_id=self.session_id,
                name=self.node_name,
                execution_order=self.execution_order,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                message_data=update_session_status_message_data,
            )

            pubsub = self.redis_service.sync_subscribe(
                f"sessions:{self.session_id}:user_input"
            )

            self.redis_service.update_session_status(
                session_id=self.session_id,
                status="wait_for_user",
                crew_id=self.crew_id,
                execution_order=self.execution_order,
                name=self.node_name,
            )
            if self.stream_writer is not None:
                self.stream_writer(graph_message)

            logger.info(f"Waiting for user input...")
            while True:
                message = pubsub.get_message()
                if message and message["type"] == "message":
                    message_data: dict = json.loads(message["data"])

                    if (
                        message_data["crew_id"] == self.crew_id
                        and message_data["node_name"] == self.node_name
                        and message_data["execution_order"] == self.execution_order
                    ):
                        logger.info(f"Received user input: {message_data}")
                        break
                time.sleep(0.1)

            update_session_status_message_data = UpdateSessionStatusMessageData(
                crew_id=self.crew_id,
                status="run",
                status_data={
                    "name": self.node_name,
                    "execution_order": self.execution_order,
                },
            )
            graph_message = GraphMessage(
                session_id=self.session_id,
                name=self.node_name,
                execution_order=self.execution_order,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                message_data=update_session_status_message_data,
            )

            if self.stream_writer is not None:
                self.stream_writer(graph_message)

            pubsub.unsubscribe(f"sessions:{self.session_id}:user_input")

            user_input = message_data.get("text", "<NO USER INPUT>")
            if user_input != "</done/>":

                user_input_with_knowledges = ""
                user_input_with_knowledges += user_input

                # TODO: make one search and combine crew_knowledge_collection_id
                # TODO: potential bugs with: classification user_input if knowledge will be added
                if agent_knowledge_collection_id is not None:
                    agent_knowledges = self.knowledge_search_service.search_knowledges(
                        sender="human_agent",
                        knowledge_collection_id=agent_knowledge_collection_id,
                        query=str(user_input),
                        search_limit=3,
                        distance_threshold=1,
                    )
                    user_input_with_knowledges += self._extract_knowledges(
                        agent_knowledges
                    )

                elif crew_knowledge_collection_id is not None:
                    crew_results = self.knowledge_search_service.search_knowledges(
                        sender="human_crew",
                        knowledge_collection_id=crew_knowledge_collection_id,
                        query=str(user_input),
                        search_limit=3,
                        distance_threshold=0.7,
                    )
                    user_input_with_knowledges += self._extract_knowledges(crew_results)

                logger.info(f"{user_input_with_knowledges=}")

                return user_input_with_knowledges

            else:
                return user_input

        return inner
