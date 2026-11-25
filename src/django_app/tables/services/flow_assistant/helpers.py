from __future__ import annotations

import re

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone
from src.shared.untrusted_content import wrap_untrusted_tool_result
from tables.models.flow_assistant_models import FlowAssistantConversation, FlowAssistantMessage
from tables.services.redis_service import RedisService

from .constants import (
    _CANCEL_KEY,
    _CANCEL_TTL_SECONDS,
    _FIRST_PARTY_OUTPUT_TOOLS,
    _MD_TABLE_PATTERN,
    _TITLE_MAX_CHARS,
)

_UNATTRIBUTED_STALE_TOOL_RESULT_STUB = (
    "[tool result from an earlier turn was omitted to save context.]"
)


def _strip_markdown_tables(text: str) -> str:
    """Remove GitHub-flavored markdown tables from text.

    Defensive — the system prompt instructs the LLM to put table data only in
    `ef_tables`, but it drifts. We strip duplicates at persistence time so
    stored conversations don't show the same data twice when re-opened.
    """
    cleaned = _MD_TABLE_PATTERN.sub("\n", text)
    # Collapse 3+ consecutive newlines to two
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _derive_title(message: str) -> str:
    """Truncate message to at most 50 characters at a word boundary, append '…' if truncated."""
    text = message.strip()
    if len(text) <= _TITLE_MAX_CHARS:
        return text
    truncated = text[:_TITLE_MAX_CHARS]
    # Walk back to the last whitespace so we don't cut mid-word.
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated + "…"


def _sanitize_for_llm(msg: dict) -> dict:
    """Return a copy of *msg* containing only OpenAI-compatible fields.

    FA persists extra per-message metadata (``ef_tables``, ``action_message``,
    ``interrupted``) for its own rendering needs.  Those fields are valid inside
    the FA database but are **not** part of the OpenAI messages schema.  Strict
    OpenAI-compatible providers (e.g. Fireworks) reject unknown message fields
    with a 400 error, so we must strip them before any LLM call.

    Whitelist approach: only emit fields that the OpenAI chat-completion API
    accepts.  Any future FA-internal field added to the message store is
    automatically excluded from outgoing LLM payloads without a separate change
    here.
    """
    role = msg.get("role", "")
    out: dict = {"role": role}

    # ``content`` is always included; allow None for tool-call assistant turns.
    if "content" in msg:
        out["content"] = msg["content"]

    # ``tool_calls`` — assistant role only (but also defensively accepted on
    # system/user per the OpenAI spec extension).
    if msg.get("tool_calls") is not None:
        out["tool_calls"] = msg["tool_calls"]

    # ``tool_call_id`` and ``name`` — tool role only.
    if msg.get("tool_call_id") is not None:
        out["tool_call_id"] = msg["tool_call_id"]
    if msg.get("name") is not None:
        out["name"] = msg["name"]

    return out


def _messages_for_llm(messages: list[dict]) -> list[dict]:
    """Return a sanitized copy of *messages* ready for the LLM.

    Three transforms are applied:

    1. **FA-internal field strip** — ``ef_tables``, ``action_message``,
       ``interrupted``, and any other non-OpenAI field are removed via
       :func:`_sanitize_for_llm`.  Strict OpenAI-compatible providers (e.g.
       Fireworks, Azure with ``strict=true``) reject unknown message fields
       with a 400 error, so stripping at the assembly boundary is the right
       place — not inside the shared LiteLLM client.

    2. **Stale tool-result eviction** — any ``tool`` message preceding the
       *last* user message is replaced with a short stub.  "Stale" is safe to
       evict here because every FA tool is a pure, idempotent read.  If a
       future tool has side effects or non-deterministic output, exclude it
       from eviction (or add a per-tool whitelist).

    3. **Untrusted-data envelope** — every other tool result is wrapped so the
       flow data, run history and error text it carries can never pose as
       instructions. Only the payload is wrapped: the stored conversation keeps
       the plain result the frontend shows. Results of the first-party tools in
       ``_FIRST_PARTY_OUTPUT_TOOLS`` are left as they are.

    A tool message is attributed only to a call in the assistant turn directly before
    its tool block, and only when exactly one call there carries its id: providers may
    send no id (``""``) or reuse one (``call_0``) across turns. A result that cannot be
    attributed this way is never exempted: from the current turn it is enveloped in full,
    from an earlier turn it becomes a generic stub that names no tool and repeats none of
    its output.
    """
    last_user_idx = -1
    for i, msg in enumerate(messages):
        if msg.get("role") == "user":
            last_user_idx = i

    result: list[dict] = []
    turn_tool_calls: list[dict] = []
    for i, msg in enumerate(messages):
        sanitized = _sanitize_for_llm(msg)
        if msg.get("role") == "tool":
            tool_call = _tool_call_answered_by(msg, turn_tool_calls)
            sanitized["content"] = _tool_content_for_llm(msg, tool_call, is_stale=i < last_user_idx)
        elif msg.get("role") == "assistant":
            turn_tool_calls = msg.get("tool_calls") or []
        else:
            # A user or system message ends the previous tool block.
            turn_tool_calls = []
        result.append(sanitized)

    return result


def _tool_call_answered_by(tool_message: dict, turn_tool_calls: list[dict]) -> dict | None:
    tool_call_id = tool_message.get("tool_call_id") or ""
    matches = [call for call in turn_tool_calls if (call.get("id") or "") == tool_call_id]
    return matches[0] if len(matches) == 1 else None


def _tool_content_for_llm(msg: dict, tool_call: dict | None, *, is_stale: bool) -> str:
    content = msg.get("content") or ""
    if is_stale and tool_call is None:
        return _UNATTRIBUTED_STALE_TOOL_RESULT_STUB
    if tool_call is None:
        return wrap_untrusted_tool_result(content)

    function = tool_call.get("function") or {}
    name = function.get("name", "")
    args = function.get("arguments", "")
    if is_stale:
        args_display = args if len(args) <= 200 else args[:200] + "…"
        return (
            f"[tool result from an earlier turn was omitted to save context. "
            f"tool: {name}, args: {args_display}. "
            f"The assistant already used this result; do not re-call unless the user "
            f"explicitly asks for fresh data.]"
        )

    if name in _FIRST_PARTY_OUTPUT_TOOLS:
        return content
    return wrap_untrusted_tool_result(content)


def _dict_to_message_row(conversation_id: int, idx: int, msg: dict) -> FlowAssistantMessage:
    """Map a legacy message dict to a FlowAssistantMessage instance (unsaved)."""
    role = msg.get("role", "user")
    content = msg.get("content", "") or ""
    row = FlowAssistantMessage(
        conversation_id=conversation_id,
        message_index=idx,
        role=role,
        content=content,
    )
    if role == "assistant":
        row.tool_calls = msg.get("tool_calls")
        row.ef_tables = msg.get("ef_tables")
        row.action_message = msg.get("action_message")
        row.interrupted = bool(msg.get("interrupted", False))
    elif role == "tool":
        row.tool_call_id = msg.get("tool_call_id") or None
        row.name = msg.get("name") or None
    elif role in ("system", "user"):
        row.tool_calls = msg.get("tool_calls")
    return row


def _load_message_dicts(conversation_id: int) -> list[dict]:
    """Load message history as a list of dicts from FlowAssistantMessage rows.

    Used by stream_reply to build its local working copy of the conversation.
    Falls back to the legacy JSONField column when no rows exist (transition window).
    """
    rows = list(
        FlowAssistantMessage.objects.filter(conversation_id=conversation_id).order_by(
            "message_index"
        )
    )
    if not rows:
        # Transition fallback: no rows yet — read from legacy column.
        conv = FlowAssistantConversation.objects.get(pk=conversation_id)
        return list(conv._messages_legacy or [])

    result = []
    for row in rows:
        msg: dict = {"role": row.role, "content": row.content}
        if row.role == "assistant":
            if row.tool_calls is not None:
                msg["tool_calls"] = row.tool_calls
            if row.ef_tables is not None:
                msg["ef_tables"] = row.ef_tables
            if row.action_message is not None:
                msg["action_message"] = row.action_message
            if row.interrupted:
                msg["interrupted"] = True
        elif row.role == "tool":
            if row.tool_call_id is not None:
                msg["tool_call_id"] = row.tool_call_id
            if row.name is not None:
                msg["name"] = row.name
        elif row.role in ("system", "user"):
            if row.tool_calls is not None:
                msg["tool_calls"] = row.tool_calls
        result.append(msg)
    return result


@sync_to_async
def _persist_messages(conversation_id: int, messages: list[dict]) -> None:
    """Atomically rewrite the conversation's message history as rows."""
    with transaction.atomic():
        FlowAssistantMessage.objects.filter(conversation_id=conversation_id).delete()
        rows = [_dict_to_message_row(conversation_id, idx, msg) for idx, msg in enumerate(messages)]
        if rows:
            FlowAssistantMessage.objects.bulk_create(rows)
        FlowAssistantConversation.objects.filter(pk=conversation_id).update(
            last_message_at=timezone.now(),
        )


async def request_cancel(conv_id: int) -> None:
    """Set the cancel flag for a conversation (TTL: 300 s)."""
    redis_service = RedisService()
    key = _CANCEL_KEY.format(conv_id=conv_id)
    await sync_to_async(redis_service.redis_client.set)(key, "1", ex=_CANCEL_TTL_SECONDS)


async def _is_cancel_requested(conv_id: int) -> bool:
    """Return True if a cancel flag is set for this conversation."""
    redis_service = RedisService()
    key = _CANCEL_KEY.format(conv_id=conv_id)
    return bool(await sync_to_async(redis_service.redis_client.get)(key))


async def _clear_cancel_flag(conv_id: int) -> None:
    """Remove the cancel flag, if present."""
    redis_service = RedisService()
    key = _CANCEL_KEY.format(conv_id=conv_id)
    await sync_to_async(redis_service.redis_client.delete)(key)
