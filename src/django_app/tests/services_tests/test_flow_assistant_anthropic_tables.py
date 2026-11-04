"""Flow Assistant tables on Anthropic models.

Anthropic closes every object in a structured-output schema, so rows that are free-form
objects can only be ``{}``. The assistant therefore asks Anthropic models for ``cells``
arrays and rebuilds flat ``rows`` after parsing.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from asgiref.sync import sync_to_async
from litellm.llms.anthropic.chat.transformation import AnthropicConfig

from rbac.models import Organization
from tables.models import Graph, LLMConfig, LLMModel, Provider
from tables.models.flow_assistant_models import (
    FlowAssistant,
    FlowAssistantConversation,
    FlowAssistantMessage,
)
from tables.services.flow_assistant import FlowAssistantService
from tables.services.flow_assistant.output_schema import (
    ANTHROPIC_FLOW_ASSISTANT_OUTPUT_SCHEMA,
    FLOW_ASSISTANT_OUTPUT_SCHEMA,
    normalize_table_cells,
    uses_anthropic_structured_output,
)
from tables.services.llm_clients.base import DoneEvent, TokenEvent

# ── normalize_table_cells (domain) ────────────────────────────────────────────

COLUMNS = [{"key": "node_id"}, {"key": "node_type"}, {"key": "node_name"}]


@pytest.mark.parametrize(
    "table, expected_rows",
    [
        (
            {"columns": COLUMNS, "cells": [["4", "start", "__start__"], ["5", "end", "end"]]},
            [
                {"node_id": "4", "node_type": "start", "node_name": "__start__"},
                {"node_id": "5", "node_type": "end", "node_name": "end"},
            ],
        ),
        # Scalar types and null survive untouched.
        (
            {"columns": COLUMNS, "cells": [[1, True, None]]},
            [{"node_id": 1, "node_type": True, "node_name": None}],
        ),
        # Ragged: short row leaves keys out, long row drops the extra cells.
        (
            {"columns": COLUMNS, "cells": [["4"], ["1", "a", "b", "extra"]]},
            [{"node_id": "4"}, {"node_id": "1", "node_type": "a", "node_name": "b"}],
        ),
        # No columns at all: nothing to key the cells by.
        ({"cells": [["a", "b"]]}, [{}]),
        ({"columns": [], "cells": [["a"]]}, [{}]),
        # A column without a usable key drops only its own cell; the others stay in place.
        (
            {"columns": [{"title": "x"}, {"key": "name"}], "cells": [["skipped", "Alice"]]},
            [{"name": "Alice"}],
        ),
        # A row that is already an object passes through; any other type becomes an empty row.
        ({"columns": COLUMNS, "cells": [{"node_id": "9"}]}, [{"node_id": "9"}]),
        ({"columns": COLUMNS, "cells": ["oops"]}, [{}]),
        ({"columns": COLUMNS, "cells": []}, []),
        ({"columns": COLUMNS, "cells": None}, []),
    ],
)
def test_cells_become_flat_rows_keyed_by_columns(table, expected_rows):
    [result] = normalize_table_cells([table])

    assert result["rows"] == expected_rows
    assert "cells" not in result


def test_other_table_keys_are_kept_when_cells_are_converted():
    table = {
        "id": "nodes",
        "columns": COLUMNS,
        "cells": [["1", "a", "b"]],
        "isSortable": False,
    }

    [result] = normalize_table_cells([table])

    assert result["id"] == "nodes"
    assert result["columns"] == COLUMNS
    assert result["isSortable"] is False
    assert "cells" in table  # the input is not mutated


def test_cells_win_over_rows_when_a_table_has_both():
    table = {"columns": COLUMNS, "rows": [{"node_id": "old"}], "cells": [["new", "a", "b"]]}

    [result] = normalize_table_cells([table])

    assert result["rows"] == [{"node_id": "new", "node_type": "a", "node_name": "b"}]
    assert "cells" not in result


@pytest.mark.parametrize("not_a_list", [None, {"cells": [["a"]]}, "text"])
def test_ef_tables_that_is_not_a_list_is_returned_unchanged(not_a_list):
    assert normalize_table_cells(not_a_list) is not_a_list


def test_tables_with_flat_rows_pass_through_unchanged():
    flat = {"columns": COLUMNS, "rows": [{"node_id": "1"}]}
    rows_only = {"rows": [{"name": "Alice"}]}

    assert normalize_table_cells([flat, rows_only]) == [flat, rows_only]
    assert normalize_table_cells([]) == []


# ── schema (contract with LiteLLM) ────────────────────────────────────────────


def _table_schema(output_schema):
    return output_schema["schema"]["properties"]["ef_tables"]["items"]


def test_anthropic_schema_can_represent_table_data_after_litellm_filtering():
    filtered = AnthropicConfig.filter_anthropic_output_schema(
        ANTHROPIC_FLOW_ASSISTANT_OUTPUT_SCHEMA["schema"]
    )

    table = filtered["properties"]["ef_tables"]["items"]
    row = table["properties"]["cells"]["items"]
    cell = row["items"]
    assert row["type"] == "array"
    assert {option["type"] for option in cell["anyOf"]} == {"string", "number", "boolean", "null"}
    assert "rows" not in table["properties"]
    assert table["required"] == ["columns", "cells"]
    # Columns keep their own properties instead of collapsing to a closed empty object.
    assert "key" in table["properties"]["columns"]["items"]["properties"]


def test_default_schema_still_declares_flat_rows_and_is_not_mutated_by_the_variant():
    table = _table_schema(FLOW_ASSISTANT_OUTPUT_SCHEMA)

    assert "rows" in table["properties"]
    assert "cells" not in table["properties"]
    assert table["required"] == ["rows"]


def test_anthropic_schema_keeps_message_and_action_message_as_in_the_default():
    default = FLOW_ASSISTANT_OUTPUT_SCHEMA["schema"]["properties"]
    anthropic = ANTHROPIC_FLOW_ASSISTANT_OUTPUT_SCHEMA["schema"]["properties"]

    assert anthropic["message"] == default["message"]
    assert anthropic["action_message"] == default["action_message"]
    assert ANTHROPIC_FLOW_ASSISTANT_OUTPUT_SCHEMA["schema"]["required"] == ["message"]


# ── provider selection ────────────────────────────────────────────────────────


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org")


def _llm_config(org, provider_name, model_name):
    provider = Provider.objects.get_or_create(name=provider_name)[0] if provider_name else None
    model = LLMModel.objects.create(name=model_name, llm_provider=provider)
    return LLMConfig.objects.create(custom_name=f"{provider_name}-cfg", model=model, org=org)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "provider_name, model_name, expected",
    [
        ("anthropic", "claude-opus-4-8", True),
        ("anthropic", "anthropic/claude-sonnet-4-6", True),
        # An OpenAI-compatible row holding a bare Claude name is routed to Anthropic by LiteLLM.
        ("openai", "claude-sonnet-4-6", True),
        ("openai", "gpt-4o", False),
        (None, "claude-sonnet-4-6", True),
        (None, "gpt-4o", False),
        ("groq", "llama-3.3-70b-versatile", False),
        ("google_ai", "gemini-flash-latest", False),
    ],
)
def test_anthropic_detection_follows_the_litellm_route(org, provider_name, model_name, expected):
    config = _llm_config(org, provider_name, model_name)

    assert uses_anthropic_structured_output(config) is expected


def test_config_without_a_model_is_not_anthropic():
    assert uses_anthropic_structured_output(None) is False
    assert uses_anthropic_structured_output(LLMConfig(model=None)) is False


@pytest.fixture
def graph(org):
    return Graph.objects.create(name="Flow", description="d", org=org)


def _table_format_section(prompt):
    return prompt.split("### `ef_tables`")[1].split("### `action_message`")[0]


@pytest.mark.django_db
def test_system_prompt_uses_cells_instructions_only_for_anthropic(graph, org):
    assistant = FlowAssistant.objects.create(
        graph=graph, llm_config=_llm_config(org, "anthropic", "claude-opus-4-8")
    )
    anthropic_prompt = FlowAssistantService().build_system_prompt(assistant)
    assistant.llm_config = _llm_config(org, "openai", "gpt-4o")
    openai_prompt = FlowAssistantService().build_system_prompt(assistant)

    assert '"cells": [["Alice", 95], ["Bob", 72]]' in anthropic_prompt
    assert '"rows": [' not in _table_format_section(anthropic_prompt)
    assert '"rows": [{"name": "Alice", "score": 95}' in openai_prompt
    assert '"cells"' not in openai_prompt


@pytest.mark.django_db
def test_system_prompt_for_assistant_without_llm_config_is_the_default_one(graph):
    assistant = FlowAssistant.objects.create(graph=graph, llm_config=None)

    prompt = FlowAssistantService().build_system_prompt(assistant)

    assert '"rows": [{"name": "Alice", "score": 95}' in prompt


# ── stream_reply (application) ────────────────────────────────────────────────

CELLS_REPLY = json.dumps(
    {
        "message": "Found 2 nodes:",
        "ef_tables": [
            {
                "id": "nodes",
                "columns": [{"key": "node_id", "title": "ID"}, {"key": "node_name"}],
                "cells": [["4", "__start__"], ["5", "end"]],
            }
        ],
        "action_message": [],
    }
)
FLAT_ROWS = [{"node_id": "4", "node_name": "__start__"}, {"node_id": "5", "node_name": "end"}]


async def _run_reply(graph, org, llm_config, reply, *, fail_after_reply=False, cancel=False):
    from django.contrib.auth import get_user_model

    from rbac.models import OrganizationUser, Role
    from rbac.models.enums import BuiltInRole

    role = await sync_to_async(Role.objects.get)(
        name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True
    )
    user = await sync_to_async(get_user_model().objects.create_user)(
        email="anthropic-tables@test.com", password="Pass1234!"
    )
    org_user = await sync_to_async(OrganizationUser.objects.create)(user=user, org=org, role=role)
    assistant = await sync_to_async(FlowAssistant.objects.create)(
        graph=graph, llm_config=llm_config
    )
    conversation = await sync_to_async(FlowAssistantConversation.objects.create)(
        flow_assistant=assistant, organization_user=org_user
    )
    await sync_to_async(FlowAssistantMessage.objects.create)(
        conversation=conversation, message_index=0, role="system", content="sys"
    )
    await sync_to_async(FlowAssistantMessage.objects.create)(
        conversation=conversation, message_index=1, role="user", content="show nodes"
    )

    async def fake_stream(messages, tools):
        yield TokenEvent(content=reply)
        if fail_after_reply:
            raise RuntimeError("connection dropped")
        yield DoneEvent()

    # Cancel checkpoints in order: before the turn (no), after the first token (yes).
    cancel_patch = (
        patch(
            "tables.services.flow_assistant.service._is_cancel_requested",
            side_effect=[False, True],
        )
        if cancel
        else nullcontext()
    )
    with (
        patch("tables.services.flow_assistant.service.get_llm_client") as mock_get_client,
        cancel_patch,
    ):
        mock_client = MagicMock()
        mock_client.stream_completion = fake_stream
        mock_get_client.return_value = mock_client
        events = []
        try:
            async for event in FlowAssistantService().stream_reply(conversation, "show nodes"):
                events.append(event)
        except RuntimeError:
            if not fail_after_reply:
                raise
    return events, mock_get_client, conversation


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_cells_reply_is_emitted_and_persisted_as_flat_rows(graph, org):
    config = await sync_to_async(_llm_config)(org, "anthropic", "claude-opus-4-8")

    events, get_client, conversation = await _run_reply(graph, org, config, CELLS_REPLY)

    [structured] = [e for e in events if e.type == "structured"]
    assert structured.ef_tables == [
        {
            "id": "nodes",
            "columns": [{"key": "node_id", "title": "ID"}, {"key": "node_name"}],
            "rows": FLAT_ROWS,
        }
    ]
    persisted = await sync_to_async(
        lambda: list(
            FlowAssistantMessage.objects.filter(conversation=conversation, role="assistant")
        )
    )()
    assert [m.ef_tables for m in persisted] == [structured.ef_tables]
    assert get_client.call_args.kwargs["output_schema"] is ANTHROPIC_FLOW_ASSISTANT_OUTPUT_SCHEMA


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_openai_reply_keeps_flat_rows_and_the_default_schema(graph, org):
    config = await sync_to_async(_llm_config)(org, "openai", "gpt-4o")
    reply = json.dumps(
        {
            "message": "Found:",
            "ef_tables": [{"columns": [{"key": "node_id"}], "rows": [{"node_id": "4"}]}],
        }
    )

    events, get_client, _ = await _run_reply(graph, org, config, reply)

    [structured] = [e for e in events if e.type == "structured"]
    assert structured.ef_tables == [{"columns": [{"key": "node_id"}], "rows": [{"node_id": "4"}]}]
    assert get_client.call_args.kwargs["output_schema"] is FLOW_ASSISTANT_OUTPUT_SCHEMA


async def _persisted_assistant_tables(conversation):
    persisted = await sync_to_async(
        lambda: list(
            FlowAssistantMessage.objects.filter(conversation=conversation, role="assistant")
        )
    )()
    return [m.ef_tables for m in persisted], [m.interrupted for m in persisted]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_cancelled_reply_persists_flat_rows(graph, org):
    config = await sync_to_async(_llm_config)(org, "anthropic", "claude-opus-4-8")

    events, _, conversation = await _run_reply(graph, org, config, CELLS_REPLY, cancel=True)

    assert events[-1].type == "done" and events[-1].interrupted
    tables, interrupted = await _persisted_assistant_tables(conversation)
    assert interrupted == [True]
    assert tables == [
        [
            {
                "id": "nodes",
                "columns": [{"key": "node_id", "title": "ID"}, {"key": "node_name"}],
                "rows": FLAT_ROWS,
            }
        ]
    ]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_reply_interrupted_by_an_error_persists_flat_rows(graph, org):
    config = await sync_to_async(_llm_config)(org, "anthropic", "claude-opus-4-8")

    _, _, conversation = await _run_reply(graph, org, config, CELLS_REPLY, fail_after_reply=True)

    tables, interrupted = await _persisted_assistant_tables(conversation)
    assert interrupted == [True]
    assert tables[0][0]["rows"] == FLAT_ROWS
    assert "cells" not in tables[0][0]


# -- prompt drift guard ------------------------------------------------------

PROMPTS_DIR = (
    Path(__file__).resolve().parents[2] / "tables" / "services" / "flow_assistant" / "prompts"
)


def _without_table_regions(text):
    """Cut the two regions that intentionally differ: the table intro and the example."""
    intro_start = text.index("twice to the user.")
    intro_end = text.index("Column options:")
    example_start = text.index('  "ef_tables": [{')
    example_end = text.index('    "isEditable": false,', example_start)
    return text[:intro_start] + text[intro_end:example_start] + text[example_end:]


def test_anthropic_prompt_matches_default_outside_the_table_regions():
    default = (PROMPTS_DIR / "rich_format.md").read_text(encoding="utf-8")
    anthropic = (PROMPTS_DIR / "rich_format_anthropic.md").read_text(encoding="utf-8")

    assert default != anthropic
    assert _without_table_regions(anthropic) == _without_table_regions(default)
