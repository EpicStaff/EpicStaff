import json
from typing import Any

import litellm
from loguru import logger
from langgraph.types import StreamWriter

from callbacks.session_callback_factory import CrewCallbackFactory
from services.crew.crew_parser_service import CrewParserService
from services.graph.events import StopEvent
from services.graph.nodes import BaseNode
from services.redis_service import RedisService
from services.knowledge_search_service import KnowledgeSearchService
from src.shared.models import CrewData

from models.state import State


def _compute_crew_cost_and_cached_tokens(crew) -> tuple[float, int]:
    """Sum real USD cost + cached-token count per agent's own model.

    Reuses the same per-agent iteration crewAI's own
    Crew.calculate_usage_metrics() does (crew.py:1091-1101) — no fork changes,
    just re-deriving per-model detail before it gets flattened into one
    crew-level aggregate.
    """
    total_cost = 0.0
    total_cached = 0
    agents = list(crew.agents) + ([crew.manager_agent] if crew.manager_agent else [])
    for agent in agents:
        if not hasattr(agent, "_token_process"):
            continue
        usage = agent._token_process.get_summary()
        total_cached += usage.cached_prompt_tokens

        model_name = getattr(getattr(agent, "llm", None), "model", None)
        if not model_name:
            continue
        try:
            prompt_cost, completion_cost = litellm.cost_per_token(
                model=model_name,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                cache_read_input_tokens=usage.cached_prompt_tokens,
            )
        except Exception:
            continue  # кастомна/self-hosted модель без цінового запису — пропускаємо, не крашимо
        total_cost += prompt_cost + completion_cost
    return total_cost, total_cached


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

        if "session_id" in input_:
            logger.warning(
                f"Crew {self.node_name}: input already defines 'session_id'="
                f"{input_['session_id']!r} — overriding with the internal "
                f"session id {self.session_id} because built-in tools (e.g. "
                "subflow_tool) depend on the injected value."
            )

        global_kwargs = {
            **input_,
            "state": {
                "variables": state["variables"].model_dump(),
                "state_history": state["state_history"],
            },
            # Exposed as a bare global (globals().get("session_id")) to
            # built-in python-code tools — e.g. subflow_tool uses it to link
            # a sub-flow run to its caller via Session.parent_session and to
            # walk the ancestor chain for a recursion guard. Additive only:
            # existing tools ignore unused globals, so this is a no-op for
            # every tool that doesn't read "session_id". Always wins over a
            # same-named flow input / tool static config (warned above) —
            # internal tools depend on the injected value being authoritative.
            "session_id": self.session_id,
        }

        crew = await self.crew_parser_service.parse_crew(
            crew_data=self.crew_data,
            session_id=self.session_id,
            crew_callback_factory=crew_callback_factory,
            inputs=input_,
            global_kwargs=global_kwargs,
            stop_event=self.stop_event,
            node_name=self.node_name,
            execution_order=execution_order,
            stream_writer=writer,
        )
        crew_output = await crew.kickoff_async(inputs=input_)

        token_usage = None
        if hasattr(crew_output, "token_usage") and crew_output.token_usage:
            total_cost, total_cached = _compute_crew_cost_and_cached_tokens(crew)
            token_usage = {
                "total_tokens": crew_output.token_usage.total_tokens,
                "prompt_tokens": crew_output.token_usage.prompt_tokens,
                "completion_tokens": crew_output.token_usage.completion_tokens,
                "successful_requests": crew_output.token_usage.successful_requests,
                "cached_prompt_tokens": total_cached,
                "total_cost_usd": total_cost,
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
