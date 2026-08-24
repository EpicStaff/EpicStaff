from __future__ import annotations

import re

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from utils.logger import logger

from tables.models.flow_assistant_models import FlowAssistantConversation, FlowAssistantMessage
from tables.services.redis_service import RedisService
from .constants import (
    _CANCEL_KEY,
    _CANCEL_TTL_SECONDS,
    _MD_TABLE_PATTERN,
    _TITLE_MAX_CHARS,
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

    Two transforms are applied:

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
    """
    # Find the index of the last user message.
    last_user_idx = -1
    for i, msg in enumerate(messages):
        if msg.get("role") == "user":
            last_user_idx = i

    # No user message or it's the very first message — return a sanitized copy.
    if last_user_idx <= 0:
        return [_sanitize_for_llm(m) for m in messages]

    # Build tool_call_id → (name, args_str) from assistant messages before the last user turn.
    call_map: dict[str, tuple[str, str]] = {}
    for msg in messages[:last_user_idx]:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id", "")
                fn = tc.get("function", {})
                call_map[tc_id] = (fn.get("name", ""), fn.get("arguments", ""))

    # Build output list, stubbing stale tool messages, sanitizing all messages.
    result: list[dict] = []
    for i, msg in enumerate(messages):
        if i >= last_user_idx or msg.get("role") != "tool":
            result.append(_sanitize_for_llm(msg))
            continue

        content = msg.get("content", "")
        if isinstance(content, str) and content.startswith(
            "[tool result from an earlier turn"
        ):
            # Already stubbed — idempotent pass-through (sanitize anyway).
            result.append(_sanitize_for_llm(msg))
            continue

        tc_id = msg.get("tool_call_id", "")
        if tc_id not in call_map:
            # Defensive: unknown call id — pass through sanitized.
            result.append(_sanitize_for_llm(msg))
            continue

        name, args = call_map[tc_id]
        args_display = args if len(args) <= 200 else args[:200] + "…"
        stub = (
            f"[tool result from an earlier turn was omitted to save context. "
            f"tool: {name}, args: {args_display}. "
            f"The assistant already used this result; do not re-call unless the user "
            f"explicitly asks for fresh data.]"
        )
        # Build the stubbed message via sanitize then override content.
        sanitized = _sanitize_for_llm(msg)
        sanitized["content"] = stub
        result.append(sanitized)

    return result


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
        FlowAssistantMessage.objects.filter(
            conversation_id=conversation_id
        ).order_by("message_index")
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
        rows = [
            _dict_to_message_row(conversation_id, idx, msg)
            for idx, msg in enumerate(messages)
        ]
        if rows:
            FlowAssistantMessage.objects.bulk_create(rows)
        FlowAssistantConversation.objects.filter(pk=conversation_id).update(
            last_message_at=timezone.now(),
        )


async def request_cancel(conv_id: int) -> None:
    """Set the cancel flag for a conversation (TTL: 300 s)."""
    redis_service = RedisService()
    key = _CANCEL_KEY.format(conv_id=conv_id)
    await sync_to_async(redis_service.redis_client.set)(
        key, "1", ex=_CANCEL_TTL_SECONDS
    )


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
