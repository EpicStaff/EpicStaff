import pytest
from unittest.mock import AsyncMock, MagicMock

from dotdict import DotDict

import services.graph.nodes.crew_node as crew_node_module
from services.graph.nodes.crew_node import CrewNode


def _make_node(session_id: int, crew_parser_service) -> CrewNode:
    return CrewNode(
        session_id=session_id,
        node_name="test_crew_node",
        stop_event=MagicMock(),
        crew_data=MagicMock(id=456),
        redis_service=MagicMock(),
        crewai_output_channel="crewai_output_channel",
        crew_parser_service=crew_parser_service,
        input_map={},
        output_variable_path="variables.output",
        knowledge_search_service=MagicMock(),
    )


def _make_state() -> dict:
    return {
        "variables": DotDict({}),
        "state_history": [],
        "system_variables": {},
        "execution_counts": {},
    }


def _make_crew_parser_service() -> MagicMock:
    """A CrewParserService double whose parse_crew() returns a crew mock with
    an awaitable kickoff_async() -- no real CrewAI / LLM call happens."""
    crew_output = MagicMock()
    crew_output.pydantic = None
    crew_output.raw = "done"
    crew_output.token_usage = None

    crew = MagicMock()
    crew.kickoff_async = AsyncMock(return_value=crew_output)

    crew_parser_service = MagicMock()
    crew_parser_service.parse_crew = AsyncMock(return_value=crew)
    return crew_parser_service


@pytest.mark.asyncio
async def test_execute_injects_internal_session_id_into_global_kwargs():
    """Pins the injection: execute() must always pass the node's own
    self.session_id through to global_kwargs["session_id"] so built-in
    python-code tools (e.g. subflow_tool's recursion guard) can read it."""
    crew_parser_service = _make_crew_parser_service()
    node = _make_node(session_id=999, crew_parser_service=crew_parser_service)

    await node.execute(
        state=_make_state(), writer=MagicMock(), execution_order=1, input_={}
    )

    _, call_kwargs = crew_parser_service.parse_crew.call_args
    assert call_kwargs["global_kwargs"]["session_id"] == 999


@pytest.mark.asyncio
async def test_execute_internal_session_id_wins_over_user_defined_and_warns(
    monkeypatch,
):
    """a user-defined 'session_id' in
    the node's input is overridden by the internal id -- but the collision
    must be logged as a warning, not silently swallowed."""
    crew_parser_service = _make_crew_parser_service()
    node = _make_node(session_id=999, crew_parser_service=crew_parser_service)

    mock_logger = MagicMock()
    monkeypatch.setattr(crew_node_module, "logger", mock_logger)

    await node.execute(
        state=_make_state(),
        writer=MagicMock(),
        execution_order=1,
        input_={"session_id": "user-supplied-value"},
    )

    _, call_kwargs = crew_parser_service.parse_crew.call_args
    assert call_kwargs["global_kwargs"]["session_id"] == 999
    assert mock_logger.warning.called
    warning_message = mock_logger.warning.call_args[0][0]
    assert "user-supplied-value" in warning_message
    assert "999" in warning_message
