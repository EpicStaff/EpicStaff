from __future__ import annotations

"""SSE event serialization for the Flow Assistant stream view.

These handlers convert internal StreamEvent dataclasses into the
{event, data} dicts the SSE response yields. Kept out of views so the
view layer stays a thin pass-through.
"""

from typing import Any, Awaitable, Callable

from asgiref.sync import sync_to_async

from tables.services.llm_clients.base import StructuredEvent
from .tools import resolve_node_display_name, resolve_subgraph_display_name


async def handle_token_event(
    event: Any,
    *,
    graph_id: int,
    node_index: dict | None,
) -> tuple[dict, bool]:
    """Token deltas -> SSE token frames."""
    return ({"event": "token", "data": {"type": "token", "content": event.content}}, False)


async def handle_tool_call_event(
    event: Any,
    *,
    graph_id: int,
    node_index: dict | None,
) -> tuple[dict, bool]:
    """Tool call -> SSE tool_call frame, enriched with node/subgraph display name hints."""
    payload: dict = {
        "type": "tool_call",
        "id": event.id,
        "name": event.name,
        "arguments": event.args,
    }
    # Enrich with display-name hints for node / subgraph lookups.
    if event.name in ("get_node", "get_edges_from", "get_edges_to"):
        node_id_raw = event.args.get("node_id")
        if node_id_raw is not None:
            try:
                hint = await sync_to_async(resolve_node_display_name)(
                    graph_id, int(node_id_raw), node_index
                )
                payload["node_name_hint"] = hint
            except (ValueError, TypeError):
                payload["node_name_hint"] = None
    elif event.name == "get_subflow":
        subgraph_node_id_raw = event.args.get("subgraph_node_id")
        if subgraph_node_id_raw is not None:
            try:
                hint = await sync_to_async(resolve_subgraph_display_name)(
                    graph_id, int(subgraph_node_id_raw)
                )
                payload["subgraph_name_hint"] = hint
            except (ValueError, TypeError):
                payload["subgraph_name_hint"] = None
    return ({"event": "tool_call", "data": payload}, False)


async def handle_tool_result_event(
    event: Any,
    *,
    graph_id: int,
    node_index: dict | None,
) -> tuple[dict, bool]:
    """Tool result -> SSE tool_result frame."""
    return (
        {
            "event": "tool_result",
            "data": {
                "type": "tool_result",
                "id": event.id,
                "name": event.name,
                "content": event.content,
            },
        },
        False,
    )


async def handle_structured_event(
    event: Any,
    *,
    graph_id: int,
    node_index: dict | None,
) -> tuple[dict, bool]:
    """Structured event -> SSE structured frame."""
    return (
        {
            "event": "structured",
            "data": {
                "type": "structured",
                "message": event.message,
                "ef_tables": event.ef_tables,
                "action_message": event.action_message,
            },
        },
        False,
    )


async def handle_done_event(
    event: Any,
    *,
    graph_id: int,
    node_index: dict | None,
) -> tuple[dict, bool]:
    """Done event -> SSE done frame. Returns terminate=True."""
    payload: dict = {"type": "done"}
    if getattr(event, "interrupted", False):
        payload["interrupted"] = True
    if getattr(event, "reasoning_observed", False):
        payload["reasoning_observed"] = True
    return ({"event": "done", "data": payload}, True)


_STREAM_EVENT_HANDLERS: dict[str, Callable[..., Awaitable[tuple[dict, bool]]]] = {
    "token": handle_token_event,
    "tool_call": handle_tool_call_event,
    "tool_result": handle_tool_result_event,
    "done": handle_done_event,
}


async def serialize_stream_event(
    event: Any,
    *,
    graph_id: int,
    node_index: dict | None,
) -> tuple[dict, bool] | None:
    """Convert one internal StreamEvent into an SSE (payload, terminate) tuple.

    Returns None for unknown event types so the caller can skip them.
    """
    # isinstance check first — StructuredEvent is dispatched by type identity,
    # not by the string 'type' attribute.
    if isinstance(event, StructuredEvent):
        return await handle_structured_event(event, graph_id=graph_id, node_index=node_index)
    handler = _STREAM_EVENT_HANDLERS.get(getattr(event, "type", None))
    if handler is None:
        return None
    return await handler(event, graph_id=graph_id, node_index=node_index)
