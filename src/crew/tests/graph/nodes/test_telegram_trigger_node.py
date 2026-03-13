import pytest
from unittest.mock import MagicMock
from services.graph.nodes.telegram_trigger_node import TelegramTriggerNode
from src.shared.models import TelegramTriggerNodeFieldData


@pytest.mark.asyncio
async def test_telegram_trigger_node_execute_success():
    fields = [
        TelegramTriggerNodeFieldData(
            parent="message", field_name="text", variable_path="variables.user_text"
        ),
        TelegramTriggerNodeFieldData(
            parent="message", field_name="message_id", variable_path="variables.msg_id"
        ),
    ]

    node = TelegramTriggerNode(
        session_id=1, node_name="test_node", stop_event=MagicMock(), field_list=fields
    )

    state = MagicMock()
    input_data = {
        "telegram_payload": {"message": {"text": "Hello world", "message_id": 123}}
    }

    with MagicMock() as mock_set_vars:
        import services.graph.nodes.telegram_trigger_node as node_module

        node_module.set_output_variables = mock_set_vars

        await node.execute(state, MagicMock(), 1, input_data)

        assert mock_set_vars.call_count == 2
        mock_set_vars.assert_any_call(
            state=state,
            output_variable_path="variables.user_text",
            output="Hello world",
        )
