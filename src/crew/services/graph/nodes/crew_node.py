import json
from typing import Any

from loguru import logger
from langgraph.types import StreamWriter

from src.crew.callbacks.session_callback_factory import CrewCallbackFactory
from src.crew.services.crew.crew_parser_service import CrewParserService
from src.crew.services.graph.events import StopEvent
from src.crew.services.graph.nodes import BaseNode
from src.crew.services.redis_service import RedisService
from src.crew.services.knowledge_search_service import KnowledgeSearchService
from src.shared.models import CrewData

from src.crew.models.state import State


class CrewNode(BaseNode):
    TYPE = "CREW"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        stop_event: StopEvent,
        crew_data: CrewData,
        redis_service: RedisService,
        crewai_output_channel: str,
        crew_parser_service: CrewParserService,
        input_map: dict,
        output_variable_path: str,
        knowledge_search_service: KnowledgeSearchService,
        stream_config: dict | None = None,
    ):
        super().__init__(
            session_id=session_id,
            node_name=node_name,
            stop_event=stop_event,
            input_map=input_map,
            output_variable_path=output_variable_path,
        )
        self.crew_data = crew_data
        self.redis_service = redis_service
        self.crewai_output_channel = crewai_output_channel
        self.crew_parser_service = crew_parser_service
        self.knowledge_search_service = knowledge_search_service
        self.stream_config = stream_config or {}

    async def execute(
        self, state: State, writer: StreamWriter, execution_order: int, input_: Any
    ):
        crew_callback_factory = CrewCallbackFactory(
            redis_service=self.redis_service,
            session_id=self.session_id,
            node_name=self.node_name,
            crew_id=self.crew_data.id,
            execution_order=execution_order,
            crewai_output_channel=self.crewai_output_channel,
            stream_writer=writer,
            knowledge_search_service=self.knowledge_search_service,
            stream_config=self.stream_config,
        )

        gloabl_kwargs = {
            **input_,
            "state": {
                "variables": state["variables"].model_dump(),
                "state_history": state["state_history"],
            },
        }

        crew = await self.crew_parser_service.parse_crew(
            crew_data=self.crew_data,
            session_id=self.session_id,
            crew_callback_factory=crew_callback_factory,
            inputs=input_,
            global_kwargs=gloabl_kwargs,
            stop_event=self.stop_event,
            node_name=self.node_name,
            execution_order=execution_order,
            stream_writer=writer,
        )
        crew_output = await crew.kickoff_async(inputs=input_)

        token_usage = None
        if hasattr(crew_output, "token_usage") and crew_output.token_usage:
            token_usage = {
                "total_tokens": crew_output.token_usage.total_tokens,
                "prompt_tokens": crew_output.token_usage.prompt_tokens,
                "completion_tokens": crew_output.token_usage.completion_tokens,
                "successful_requests": crew_output.token_usage.successful_requests,
            }

            logger.info(f"Crew {self.node_name} token usage: {token_usage}")

        output = (
            json.loads(crew_output.pydantic.model_dump_json())
            if crew_output.pydantic
            else {"raw": crew_output.raw}
        )
        if "message" not in output:
            output["message"] = crew_output.raw
        if token_usage:
            output["token_usage"] = token_usage

        return output

    def update_state_history(self, state, type, name, input, output, **kwargs):
        return super().update_state_history(
            state=state,
            type=type,
            name=name,
            input=input,
            output=output,
            crew_id=self.crew_data.id,
        )
