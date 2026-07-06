from __future__ import annotations

"""
FlowAssistantService — the service layer for the Flow Assistant feature.

Responsibilities:
  - Provisioning FlowAssistant rows (get_or_create)
  - Generating the persona system prompt from flow metadata
  - Starting conversations
  - Running the LLM reply loop with tool-calling support
"""

import json
from datetime import timedelta
from typing import AsyncIterator

from asgiref.sync import sync_to_async
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from utils.logger import logger

from tables.exceptions import LLMConfigMissingError, LLMConfigInvalidError, ToolExecutionError
from tables.models.flow_assistant_models import (
    FlowAssistant,
    FlowAssistantConversation,
    FlowAssistantMessage,
)
from tables.services.llm_clients import (
    DoneEvent,
    StreamEvent,
    StructuredEvent,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
    UnsupportedLLMProviderError,
    get_llm_client,
)
from . import partial_json as _partial_json
from .tools import _NODE_TABLES, _TOOL_CALLABLES, TOOL_SPECS
from .constants import _MAX_TOOL_ITERATIONS, _REASONING_EMPTY_HINT
from .helpers import (
    _clear_cancel_flag,
    _derive_title,
    _is_cancel_requested,
    _load_message_dicts,
    _messages_for_llm,
    _persist_messages,
    _strip_markdown_tables,
)
from .node_registry import NODE_RELATED_NAMES
from .system_prompt import SystemPromptInputs, build_system_prompt


# ── Service ───────────────────────────────────────────────────────────────────


class FlowAssistantService:
    """Service for the Flow Assistant feature.

    Not a singleton — each request may instantiate a fresh one; the service is
    stateless beyond what's passed to its methods.
    """

    def get_or_create(self, graph_id: int) -> FlowAssistant:
        """Return the FlowAssistant for graph_id, creating it lazily if missing.

        Raises Graph.DoesNotExist if the graph does not exist.
        """
        from tables.models.graph_models import Graph

        graph = Graph.objects.get(pk=graph_id)
        assistant, _ = FlowAssistant.objects.get_or_create(graph=graph)
        return assistant

    def build_system_prompt(self, flow_assistant: FlowAssistant) -> str:
        """Generate the persona system prompt from live flow metadata.

        Always builds from current graph data — no caching so node additions
        are visible immediately per conversation.start.
        """
        graph = flow_assistant.graph

        # Node counts via single query per related manager
        node_counts: dict[str, int] = {}
        for label, rel in NODE_RELATED_NAMES:
            manager = getattr(graph, rel, None)
            if manager is not None:
                count = manager.count()
                if count:
                    node_counts[label] = count

        subflows = [
            f"  - {sn.subgraph.name}: {sn.subgraph.description}"
            for sn in graph.subgraph_node_list.select_related("subgraph").all()
            if sn.subgraph
        ]

        node_summary_lines = [
            f"  - {label}: {count}" for label, count in node_counts.items()
        ]
        node_summary = (
            "\n".join(node_summary_lines) if node_summary_lines else "  (none)"
        )
        subflow_summary = "\n".join(subflows) if subflows else "  (none)"
        description = graph.description or "(no description provided)"

        # Build "Nodes in this flow" list — up to 30 entries, sorted by (type, id).
        node_tuples: list[tuple[str, int, str]] = []
        for node_type, model_cls, has_db_node_name in _NODE_TABLES:
            fields = ["id", "node_name"] if has_db_node_name else ["id"]
            for node in model_cls.objects.filter(graph_id=graph.pk).only(*fields):
                node_tuples.append((node_type, node.pk, getattr(node, "node_name", "")))
        node_tuples.sort(key=lambda t: (t[0], t[1]))

        _MAX_NODES_IN_PROMPT = 30
        if not node_tuples:
            nodes_section = "Nodes in this flow:\n  (none)"
        else:
            visible = node_tuples[:_MAX_NODES_IN_PROMPT]
            remainder = len(node_tuples) - len(visible)
            lines = [
                f'  - id={node_id} type={node_type} name="{name}"'
                for node_type, node_id, name in visible
            ]
            if remainder:
                lines.append(
                    f"  ... ({remainder} more — call the get_flow_overview tool to see all)"
                )
            nodes_section = "Nodes in this flow:\n" + "\n".join(lines)

        now = timezone.now()
        today_iso = now.date().isoformat()
        yesterday_iso = (now - timedelta(days=1)).date().isoformat()
        tomorrow_iso = (now + timedelta(days=1)).date().isoformat()

        inputs = SystemPromptInputs(
            flow_name=graph.name,
            flow_description=description,
            today_iso=today_iso,
            yesterday_iso=yesterday_iso,
            tomorrow_iso=tomorrow_iso,
            node_summary=node_summary,
            nodes_section=nodes_section,
            subflow_summary=subflow_summary,
        )
        return build_system_prompt(inputs)

    def start_conversation(
        self, flow_assistant: FlowAssistant, organization_user
    ) -> FlowAssistantConversation:
        """Create a new conversation, seeding the system prompt as the first message."""
        system_prompt = self.build_system_prompt(flow_assistant)
        # Count prior conversations by a *different* user (not a different
        # org membership of the same user) — the relevant security signal is
        # whether data from a different human user is present.
        other_user_count = (
            FlowAssistantConversation.objects.filter(flow_assistant=flow_assistant)
            .exclude(organization_user__user_id=organization_user.user_id)
            .count()
        )
        if other_user_count > 0:
            logger.info(
                "FlowAssistant {} (graph {}): user {} starting new conversation; {} prior conversation(s) by other users.",
                flow_assistant.pk,
                flow_assistant.graph_id,
                organization_user.user_id,
                other_user_count,
            )
        conversation = FlowAssistantConversation.objects.create(
            flow_assistant=flow_assistant,
            organization_user=organization_user,
        )
        FlowAssistantMessage.objects.create(
            conversation=conversation,
            message_index=0,
            role="system",
            content=system_prompt,
        )
        logger.info(
            "Started FlowAssistantConversation {} for graph {}",
            conversation.pk,
            flow_assistant.graph_id,
        )
        return conversation

    def apply_title_if_missing(
        self, conversation: FlowAssistantConversation, message: str
    ) -> None:
        """Set conversation.title from the first user message if not yet set.

        Writes to DB only when a title is actually assigned.
        """
        if conversation.title:
            return
        title = _derive_title(message)
        conversation.title = title
        conversation.save(update_fields=["title"])

    def append_user_message(
        self, conversation: FlowAssistantConversation, content: str
    ) -> FlowAssistantMessage:
        """Append a user message to the conversation as a new FlowAssistantMessage row.

        Owns the transaction: creates the row at the next message_index AND bumps
        last_message_at in a single atomic block. Returns the created row.
        """
        with transaction.atomic():
            next_idx_result = conversation.message_rows.aggregate(m=Max("message_index"))
            next_idx = next_idx_result["m"]
            next_idx = 0 if next_idx is None else next_idx + 1
            row = FlowAssistantMessage.objects.create(
                conversation=conversation,
                message_index=next_idx,
                role="user",
                content=content,
            )
            conversation.last_message_at = timezone.now()
            conversation.save(update_fields=["last_message_at"])
        return row

    async def stream_reply(
        self,
        conversation: FlowAssistantConversation,
        user_message: str,
    ) -> AsyncIterator[StreamEvent]:
        """Stream the LLM reply for the given user message.

        The caller is responsible for having already persisted ``user_message``
        to ``conversation.messages`` before calling this method.  This method
        builds a local working copy of the message history (no mutation of the
        model object), appends assistant / tool messages to that local list as
        the turn progresses, and persists the final state once atomically at the
        end via an UPDATE query — so the model object is never left in an
        inconsistent in-memory state visible to concurrent readers.
        """
        from .output_schema import FLOW_ASSISTANT_OUTPUT_SCHEMA

        flow_assistant = await sync_to_async(
            lambda: FlowAssistant.objects.select_related(
                "graph", "llm_config__model__llm_provider"
            ).get(pk=conversation.flow_assistant_id)
        )()

        if flow_assistant.llm_config is None:
            raise LLMConfigMissingError(
                f"FlowAssistant for graph {flow_assistant.graph_id} has no llm_config set."
            )

        try:
            client = get_llm_client(
                flow_assistant.llm_config,
                output_schema=FLOW_ASSISTANT_OUTPUT_SCHEMA,
            )
        except UnsupportedLLMProviderError as exc:
            raise LLMConfigInvalidError(str(exc)) from exc

        graph_id = flow_assistant.graph_id

        # Build a local working copy from FlowAssistantMessage rows.
        # The user message is already present as a row (written by SendMessageView
        # before the SSE ticket was issued).
        working_messages: list[dict] = await sync_to_async(_load_message_dicts)(
            conversation.pk
        )

        assistant_content_parts: list[str] = []

        # Accumulates raw JSON tokens emitted by the model when response_format
        # is active.  Only populated during the final (non-tool-calling) turn.
        json_buffer: str = ""
        # Tracks how many characters of the `message` field we have already
        # forwarded as TokenEvents so we can emit only the delta each time.
        last_emitted_message_len: int = 0

        # Defensive: clear any stale cancel flag left from a previous turn.
        await _clear_cancel_flag(conversation.pk)

        # Guards against double-persist: set to True once _persist_messages has
        # been called so the finally block skips the disconnect-persist path.
        persisted_already: bool = False

        # Per-turn aggregates for the reasoning-empty hint gate.
        # These persist across tool-call iterations within a single turn.
        reasoning_observed_this_turn: bool = False
        tool_calls_this_turn: int = 0

        # True once working_messages has gained tool_call or tool entries during
        # this turn — used by the finally block to decide whether a partial
        # persist is worth issuing even when assistant_content_parts is empty.
        working_messages_dirty: bool = False

        # current_content accumulates tokens within one LLM iteration.  It is
        # defined here so the finally block can observe in-flight content even
        # when CancelledError interrupts the inner async-for before we reach the
        # `text_chunk = "".join(current_content)` line.
        current_content: list[str] = []

        try:
            # Tool-calling loop: keep looping until a DoneEvent with no tool calls
            iteration_count = 0
            while True:
                iteration_count += 1
                if iteration_count > _MAX_TOOL_ITERATIONS:
                    logger.warning(
                        "Flow Assistant tool-call loop hit max iterations ({}) for conversation {}",
                        _MAX_TOOL_ITERATIONS,
                        conversation.pk,
                    )
                    yield TokenEvent(
                        content=(
                            "Stopped: too many tool calls in a single turn. The assistant "
                            "seems to be looping — try rephrasing your question."
                        )
                    )
                    yield DoneEvent()
                    return

                # ── Outer-loop cancel checkpoint ─────────────────────────────
                if await _is_cancel_requested(conversation.pk):
                    partial_content = "".join(assistant_content_parts).strip()
                    partial: dict = {
                        "role": "assistant",
                        "content": partial_content or "",
                        "interrupted": True,
                    }
                    structured_payload = _partial_json.try_parse_full(json_buffer)
                    if structured_payload is not None:
                        partial["ef_tables"] = structured_payload.get("ef_tables") or []
                        partial["action_message"] = (
                            structured_payload.get("action_message") or []
                        )
                    if (
                        partial_content
                        or partial.get("ef_tables")
                        or partial.get("action_message")
                    ):
                        working_messages.append(partial)
                    await _persist_messages(conversation.pk, working_messages)
                    persisted_already = True
                    await _clear_cancel_flag(conversation.pk)
                    yield DoneEvent(interrupted=True)
                    return

                current_content = []  # reset for each iteration
                current_tool_calls: list[dict] = []
                is_final_turn = True  # assume final until we see tool calls
                cancel_inner: bool = False  # set when cancel detected mid-stream

                payload = _messages_for_llm(working_messages)
                async for event in client.stream_completion(payload, TOOL_SPECS):
                    if isinstance(event, DoneEvent):
                        if event.reasoning_observed:
                            reasoning_observed_this_turn = True
                        break
                    elif isinstance(event, ToolCallEvent):
                        is_final_turn = False
                        current_tool_calls.append(
                            {"id": event.id, "name": event.name, "args": event.args}
                        )
                        tool_calls_this_turn += 1
                        yield event
                    else:
                        # TokenEvent — the model is emitting content.
                        # When structured output is active the content is raw JSON;
                        # we extract and forward only the `message` field delta so
                        # the frontend's existing token-append logic keeps working.
                        current_content.append(event.content)
                        if is_final_turn:
                            json_buffer += event.content
                            current_message = _partial_json.extract_message_field(
                                json_buffer
                            )
                            if len(current_message) > last_emitted_message_len:
                                delta = current_message[last_emitted_message_len:]
                                last_emitted_message_len = len(current_message)
                                yield event.__class__(content=delta)
                        else:
                            # During tool-calling turns the model emits plain text
                            # (its "thinking" content, if any) — forward as-is.
                            yield event

                    # ── Inner-loop cancel checkpoint ─────────────────────────
                    if await _is_cancel_requested(conversation.pk):
                        cancel_inner = True
                        break

                text_chunk = "".join(current_content)
                assistant_content_parts.append(text_chunk)

                if cancel_inner:
                    partial_content = "".join(assistant_content_parts).strip()
                    partial = {
                        "role": "assistant",
                        "content": partial_content or "",
                        "interrupted": True,
                    }
                    structured_payload = _partial_json.try_parse_full(json_buffer)
                    if structured_payload is not None:
                        partial["ef_tables"] = structured_payload.get("ef_tables") or []
                        partial["action_message"] = (
                            structured_payload.get("action_message") or []
                        )
                    if (
                        partial_content
                        or partial.get("ef_tables")
                        or partial.get("action_message")
                    ):
                        working_messages.append(partial)
                    await _persist_messages(conversation.pk, working_messages)
                    persisted_already = True
                    await _clear_cancel_flag(conversation.pk)
                    yield DoneEvent(interrupted=True)
                    return

                if not current_tool_calls:
                    # No tool calls — we're done with the loop
                    break

                # Reset per-turn json state for the next iteration (tool call turns
                # don't produce the final JSON so the buffer is irrelevant there).
                json_buffer = ""
                last_emitted_message_len = 0

                # Record the assistant turn with tool calls in the local working list
                tool_calls_block = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["args"]),
                        },
                    }
                    for tc in current_tool_calls
                ]
                working_messages.append(
                    {
                        "role": "assistant",
                        "content": text_chunk or None,
                        "tool_calls": tool_calls_block,
                    }
                )
                working_messages_dirty = True

                # Execute each tool and append results to the local working list
                for tc in current_tool_calls:
                    tool_name = tc["name"]
                    tool_args = tc["args"]
                    tool_callable = _TOOL_CALLABLES.get(tool_name)

                    if tool_callable is None:
                        tool_result_content = json.dumps(
                            {"error": f"Unknown tool '{tool_name}'"}
                        )
                    else:
                        try:
                            raw_result = await sync_to_async(tool_callable)(
                                graph_id, **tool_args
                            )
                            tool_result_content = json.dumps(
                                raw_result, cls=DjangoJSONEncoder
                            )
                        except Exception as exc:
                            logger.warning(
                                "Tool {} raised {}: {}",
                                tool_name,
                                type(exc).__name__,
                                exc,
                            )
                            tool_result_content = json.dumps(
                                {"error": str(exc)}, cls=DjangoJSONEncoder
                            )

                    result_event = ToolResultEvent(
                        id=tc["id"],
                        name=tool_name,
                        content=tool_result_content,
                    )
                    yield result_event

                    working_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": tool_result_content,
                        }
                    )
                    working_messages_dirty = True

            # Parse the full JSON buffer to extract the structured payload.
            # Gracefully degrade: if parsing fails (e.g. the model ignored the
            # response_format schema), fall back to the raw streamed text.
            structured_payload = _partial_json.try_parse_full(json_buffer)

            if structured_payload is not None:
                final_text = structured_payload.get("message", "").strip()
                ef_tables: list = structured_payload.get("ef_tables") or []
                action_message: list = structured_payload.get("action_message") or []
                if ef_tables and final_text:
                    final_text = _strip_markdown_tables(final_text)
                # Emit the structured event before DoneEvent so the frontend can
                # render rich content (tables, action buttons, prompt chips).
                yield StructuredEvent(
                    message=final_text,
                    ef_tables=ef_tables,
                    action_message=action_message,
                )
            else:
                # Fallback: treat accumulated raw content as plain text.
                if json_buffer:
                    logger.warning(
                        "FlowAssistantService: could not parse LLM JSON buffer as "
                        "structured output; falling back to raw text. "
                        "Buffer length: {} chars.",
                        len(json_buffer),
                    )
                final_text = "".join(assistant_content_parts).strip()
                ef_tables = []
                action_message = []
                # Mirror the structured branch: emit one terminal event so the
                # frontend receives the assembled text even when the model
                # ignored the response_format schema (e.g. non-JSON free-text
                # from a proxy-forwarded model that drops response_format).
                if final_text:
                    yield StructuredEvent(
                        message=final_text,
                        ef_tables=[],
                        action_message=[],
                    )

            # Append final assistant reply to local working list.
            # Include ef_tables / action_message when present so the persisted
            # history faithfully reflects the structured response.
            if final_text:
                assistant_msg: dict = {"role": "assistant", "content": final_text}
                if ef_tables:
                    assistant_msg["ef_tables"] = ef_tables
                if action_message:
                    assistant_msg["action_message"] = action_message
                working_messages.append(assistant_msg)

            # Reasoning-empty hint gate: model spent its budget on the
            # reasoning channel and produced no productive output (no text,
            # no structured fields, no tool calls). Yield a transient
            # TokenEvent so the FE renders it in the otherwise-empty bubble.
            # NOT appended to working_messages — keeps next-turn context
            # clean (the model on the user's next message won't see a fake
            # "assistant said X").
            if (
                reasoning_observed_this_turn
                and tool_calls_this_turn == 0
                and not final_text
                and not ef_tables
                and not action_message
            ):
                yield TokenEvent(content=_REASONING_EMPTY_HINT)

            # Single atomic persist — write the completed history in one UPDATE.
            # Never mutate conversation.messages in place before this point.
            await _persist_messages(conversation.pk, working_messages)
            persisted_already = True

            yield DoneEvent()

        finally:
            # Disconnect-persist: if the connection dropped before we naturally
            # completed (browser refresh, tab close, network error), persist
            # whatever partial state we have so the conversation is not lost.
            if not persisted_already:
                # assistant_content_parts holds text from completed iterations.
                # current_content holds in-flight tokens from the current iteration
                # that were never appended to assistant_content_parts (CancelledError
                # exits the inner async-for before we reach that assignment).
                partial_content = (
                    "".join(assistant_content_parts) + "".join(current_content)
                ).strip()
                if partial_content or working_messages_dirty:
                    partial = {
                        "role": "assistant",
                        "content": partial_content or "",
                        "interrupted": True,
                    }
                    structured_payload = _partial_json.try_parse_full(json_buffer)
                    if structured_payload is not None:
                        partial["ef_tables"] = structured_payload.get("ef_tables") or []
                        partial["action_message"] = (
                            structured_payload.get("action_message") or []
                        )
                    if (
                        partial_content
                        or partial.get("ef_tables")
                        or partial.get("action_message")
                    ):
                        working_messages.append(partial)
                try:
                    await _persist_messages(conversation.pk, working_messages)
                except Exception as exc:
                    logger.warning(
                        "FA disconnect-persist failed for conv {}: {}",
                        conversation.pk,
                        exc,
                    )
                await _clear_cancel_flag(conversation.pk)
