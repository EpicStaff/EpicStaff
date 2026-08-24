import json
from unittest.mock import MagicMock, patch

import pytest
from crewai.agents.parser import AgentAction

from callbacks.session_callback_factory import (
    CrewCallbackFactory,
    FINDINGS_MARKER_KEY,
    FINDINGS_MESSAGE_TYPE,
    MAX_FINDINGS_RESULT_BYTES,
)


def make_agent_action(tool: str, result) -> AgentAction:
    action = AgentAction(thought="thinking", tool=tool, tool_input="{}", text="text")
    action.result = result
    return action


@pytest.fixture
def callback_factory():
    return CrewCallbackFactory(
        session_id=1,
        node_name="node_a",
        crew_id=2,
        execution_order=3,
        redis_service=MagicMock(),
        knowledge_search_service=MagicMock(),
        crewai_output_channel="crewai_output",
        stream_writer=MagicMock(),
        stream_config={},
    )


def custom_message_calls(callback_factory):
    """Return the message_data dicts passed to add_custom_message (the seam
    used for findings, distinct from the always-published 'agent' message)."""
    calls = []
    for call in callback_factory.stream_writer.call_args_list:
        graph_message = call.args[0]
        if isinstance(graph_message.message_data, dict):
            calls.append(graph_message.message_data)
    return calls


class TestFindingsMessageRecognition:
    def test_findings_marker_publishes_typed_message(self, callback_factory):
        step_callback = callback_factory.get_step_callback(agent_id=5)

        findings_payload = {
            FINDINGS_MARKER_KEY: "findings",
            "title": "Security Review",
            "summary": None,
            "findings": [
                {
                    "title": "SQL injection risk",
                    "severity": "high",
                    "category": None,
                    "file": "a.py",
                    "line": 12,
                    "detail": None,
                }
            ],
            "total_submitted": 1,
            "total_returned": 1,
            "truncated": False,
            "message": "Reported 1 finding(s).",
        }

        action = make_agent_action(
            tool="Report Findings Tool", result=json.dumps(findings_payload)
        )
        step_callback(action)

        published = custom_message_calls(callback_factory)
        findings_messages = [
            m for m in published if m.get("message_type") == FINDINGS_MESSAGE_TYPE
        ]
        assert len(findings_messages) == 1

        message_data = findings_messages[0]
        assert FINDINGS_MARKER_KEY not in message_data
        assert message_data["title"] == "Security Review"
        assert message_data["findings"][0]["severity"] == "high"
        assert message_data["total_returned"] == 1

    def test_non_findings_tool_result_does_not_publish_findings_message(
        self, callback_factory
    ):
        step_callback = callback_factory.get_step_callback(agent_id=5)

        action = make_agent_action(tool="Some Other Tool", result="plain text result")
        step_callback(action)

        published = custom_message_calls(callback_factory)
        assert all(m.get("message_type") != FINDINGS_MESSAGE_TYPE for m in published)

    def test_dict_result_without_marker_key_does_not_publish_findings_message(
        self, callback_factory
    ):
        step_callback = callback_factory.get_step_callback(agent_id=5)

        action = make_agent_action(
            tool="Some Json Tool", result=json.dumps({"some": "data"})
        )
        step_callback(action)

        published = custom_message_calls(callback_factory)
        assert all(m.get("message_type") != FINDINGS_MESSAGE_TYPE for m in published)

    def test_malformed_json_result_does_not_raise(self, callback_factory):
        step_callback = callback_factory.get_step_callback(agent_id=5)

        action = make_agent_action(tool="Broken Tool", result="{not valid json")

        # Must not raise - errors are swallowed and logged.
        step_callback(action)

        published = custom_message_calls(callback_factory)
        assert all(m.get("message_type") != FINDINGS_MESSAGE_TYPE for m in published)

    def test_empty_result_does_not_raise(self, callback_factory):
        step_callback = callback_factory.get_step_callback(agent_id=5)

        action = make_agent_action(tool="Some Tool", result="")
        step_callback(action)

        published = custom_message_calls(callback_factory)
        assert all(m.get("message_type") != FINDINGS_MESSAGE_TYPE for m in published)

    def test_agent_message_still_published_alongside_findings_message(
        self, callback_factory
    ):
        step_callback = callback_factory.get_step_callback(agent_id=5)

        findings_payload = {
            FINDINGS_MARKER_KEY: "findings",
            "findings": [{"title": "x", "severity": "info"}],
            "total_submitted": 1,
            "total_returned": 1,
            "truncated": False,
            "message": "Reported 1 finding(s).",
        }
        action = make_agent_action(
            tool="Report Findings Tool", result=json.dumps(findings_payload)
        )
        step_callback(action)

        message_types = []
        for call in callback_factory.stream_writer.call_args_list:
            graph_message = call.args[0]
            data = graph_message.message_data
            if isinstance(data, dict):
                message_types.append(data.get("message_type"))
            else:
                message_types.append(getattr(data, "message_type", None))

        assert "agent" in message_types
        assert FINDINGS_MESSAGE_TYPE in message_types

    def test_huge_non_json_result_is_skipped_without_full_parse(self, callback_factory):
        """A large non-JSON string (e.g. a file dump) must be rejected by the
        cheap prefix/size pre-checks before json.loads is ever called."""
        step_callback = callback_factory.get_step_callback(agent_id=5)

        huge_non_json = "x" * (MAX_FINDINGS_RESULT_BYTES * 2)
        action = make_agent_action(tool="Dump Tool", result=huge_non_json)

        with patch("callbacks.session_callback_factory.json.loads") as mock_loads:
            step_callback(action)
            mock_loads.assert_not_called()

        published = custom_message_calls(callback_factory)
        assert all(m.get("message_type") != FINDINGS_MESSAGE_TYPE for m in published)

    def test_normal_findings_payload_still_parsed_and_published(self, callback_factory):
        """Sanity check that the new pre-checks don't interfere with a
        normal-sized, well-formed findings payload."""
        step_callback = callback_factory.get_step_callback(agent_id=5)

        findings_payload = {
            FINDINGS_MARKER_KEY: "findings",
            "title": "Normal Review",
            "findings": [
                {"title": "minor issue", "severity": "low", "file": "b.py", "line": 3}
            ],
            "total_submitted": 1,
            "total_returned": 1,
            "truncated": False,
            "message": "Reported 1 finding(s).",
        }
        action = make_agent_action(
            tool="Report Findings Tool", result=json.dumps(findings_payload)
        )

        with patch(
            "callbacks.session_callback_factory.json.loads",
            wraps=json.loads,
        ) as mock_loads:
            step_callback(action)
            mock_loads.assert_called_once()

        published = custom_message_calls(callback_factory)
        findings_messages = [
            m for m in published if m.get("message_type") == FINDINGS_MESSAGE_TYPE
        ]
        assert len(findings_messages) == 1
        assert findings_messages[0]["title"] == "Normal Review"

    def test_oversize_valid_findings_json_is_skipped_by_size_cap(
        self, callback_factory
    ):
        """Documents the size-cap bound: even a well-formed findings payload
        (starts with '{', has the marker key) is skipped without parsing if
        it exceeds MAX_FINDINGS_RESULT_BYTES, since a real findings payload
        is bounded by the tool's own caps."""
        step_callback = callback_factory.get_step_callback(agent_id=5)

        oversized_payload = {
            FINDINGS_MARKER_KEY: "findings",
            "title": "Oversized Review",
            "findings": [{"title": "x", "severity": "info"}],
            "total_submitted": 1,
            "total_returned": 1,
            "truncated": False,
            "message": "Reported 1 finding(s).",
            # Padding to push the serialized payload past the size cap while
            # keeping it valid JSON starting with '{'.
            "padding": "y" * (MAX_FINDINGS_RESULT_BYTES + 1000),
        }
        result = json.dumps(oversized_payload)
        assert len(result) > MAX_FINDINGS_RESULT_BYTES

        action = make_agent_action(tool="Report Findings Tool", result=result)

        with patch("callbacks.session_callback_factory.json.loads") as mock_loads:
            step_callback(action)
            mock_loads.assert_not_called()

        published = custom_message_calls(callback_factory)
        assert all(m.get("message_type") != FINDINGS_MESSAGE_TYPE for m in published)
