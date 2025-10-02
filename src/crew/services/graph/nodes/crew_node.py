import json
from typing import override
from callbacks.session_callback_factory import CrewCallbackFactory
from services.crew.crew_parser_service import CrewParserService
from services.redis_service import RedisService
from services.knowledge_search_service import KnowledgeSearchService
from models.request_models import CrewData
from .base_node import *
from models.state import *


class CrewNode(BaseNode):
    TYPE = "CREW"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        crew_data: CrewData,
        redis_service: RedisService,
        crewai_output_channel: str,
        crew_parser_service: CrewParserService,
        input_map: dict,
        output_variable_path: str,
        knowledge_search_service: KnowledgeSearchService,
    ):
        super().__init__(
            session_id=session_id,
            node_name=node_name,
            input_map=input_map,
            output_variable_path=output_variable_path,
        )
        self.crew_data = crew_data
        self.redis_service = redis_service
        self.crewai_output_channel = crewai_output_channel
        self.crew_parser_service = crew_parser_service
        self.knowledge_search_service = knowledge_search_service

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
        )
        crew_output = await crew.kickoff_async(inputs=input_)

        output = (
            json.loads(crew_output.pydantic.model_dump_json())
            if crew_output.pydantic
            else {"raw": crew_output.raw}
        )
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
