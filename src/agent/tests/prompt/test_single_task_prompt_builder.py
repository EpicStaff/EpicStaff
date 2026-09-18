"""
Tests for SingleTaskPromptBuilder.
"""

from __future__ import annotations

import json

import pytest

from app.prompt.single_task import SingleTaskPromptBuilder
from shared.models.agent_service import AgentSpec, ContextAttachment
from shared.models.ai_providers import LLMConfigData, LLMData


def _agent_spec(
    instructions: str = "Research thoroughly.",
) -> AgentSpec:
    return AgentSpec(
        id=12,
        name="researcher",
        instructions=instructions,
        llm=LLMData(provider="openai", config=LLMConfigData(model="gpt-4o")),
    )


def test_build_no_attachments_no_schema():
    builder = SingleTaskPromptBuilder()
    agent = _agent_spec()
    messages = builder.build(agent, instructions="Do X")

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[0]["content"].startswith(
        f"Your name is {agent.name}.\nThese are instructions you should follow: {agent.instructions}"
    )
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Do X"


def test_system_prompt_contains_trust_directive():
    builder = SingleTaskPromptBuilder()
    agent = _agent_spec()
    messages = builder.build(agent, instructions="Do X")

    system_content = messages[0]["content"]
    assert "untrusted data" in system_content
    assert "tools" in system_content
    assert "knowledge search" in system_content
    assert "MCP" in system_content


def test_build_with_output_schema():
    builder = SingleTaskPromptBuilder()
    agent = _agent_spec()
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    messages = builder.build(agent, instructions="Summarize.", output_schema=schema)

    user_content = messages[-1]["content"]
    assert "Summarize." in user_content
    assert json.dumps(schema) in user_content


def test_build_with_attachments():
    builder = SingleTaskPromptBuilder()
    agent = _agent_spec()
    attachments = [
        ContextAttachment(role="user", content="Context snippet A", source="rag:1"),
        ContextAttachment(role="system", content="Extra system info", source="rag:2"),
    ]
    messages = builder.build(agent, instructions="Analyze.", attachments=attachments)

    assert len(messages) == 4  # system + 2 attachments + user
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "[context source: rag:1]\nContext snippet A"
    assert messages[2]["role"] == "system"
    assert messages[2]["content"] == "[context source: rag:2]\nExtra system info"
    assert messages[3]["role"] == "user"
    assert messages[3]["content"] == "Analyze."


def test_system_message_content():
    builder = SingleTaskPromptBuilder()
    agent = _agent_spec(instructions="Analyze data carefully.")
    messages = builder.build(agent, instructions="Run analysis.")

    assert messages[0]["content"].startswith(
        f"Your name is {agent.name}.\nThese are instructions you should follow: {agent.instructions}"
    )
