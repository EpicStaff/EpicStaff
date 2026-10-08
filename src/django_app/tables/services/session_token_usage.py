"""LLM token usage of sessions: where a graph message carries it, and the running total.

The running total lives in a Redis hash per session (``session_token_usage_key``) that
``GraphMessageStore`` adds to as it stores messages. Summing in Redis instead of
re-reading the messages lets the status handler get a session's full total with one
HGETALL, however long the run took.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

import redis
from src.shared.redis_keys import (
    session_token_usage_counted_messages_key,
    session_token_usage_key,
)

TOKEN_COUNT_FIELDS = (
    "total_tokens",
    "prompt_tokens",
    "completion_tokens",
    "successful_requests",
    "cached_prompt_tokens",
)
COST_FIELD = "total_cost_usd"

# Long enough for any run plus a late status redelivery; refreshed on every addition.
SESSION_TOKEN_USAGE_TTL_SECONDS = 24 * 60 * 60


def empty_token_usage() -> dict:
    return {**dict.fromkeys(TOKEN_COUNT_FIELDS, 0), COST_FIELD: 0.0}


def extract_token_usage(message_data: dict | None) -> dict | None:
    """Return the token usage a graph message carries, or None.

    Agent and task nodes put it under ``output.token_usage``; other messages may carry
    it at the top level of ``message_data``.
    """
    message_data = message_data or {}
    output = message_data.get("output")
    if isinstance(output, dict) and "token_usage" in output:
        return output["token_usage"] or None
    return message_data.get("token_usage") or None


def sum_token_usage(message_data_list: Iterable[dict | None]) -> dict:
    """Sum the token usage of graph messages; fields a message lacks count as zero."""
    total_usage = empty_token_usage()
    for message_data in message_data_list:
        token_usage = extract_token_usage(message_data)
        if not token_usage:
            continue
        for field in TOKEN_COUNT_FIELDS:
            total_usage[field] += int(token_usage.get(field) or 0)
        total_usage[COST_FIELD] += float(token_usage.get(COST_FIELD) or 0)
    return total_usage


@dataclass(frozen=True)
class MessageTokenUsage:
    """The token usage one graph message carries, as ``sum_token_usage`` returns it."""

    session_id: int
    message_uuid: str
    token_usage: dict


class SessionTokenUsageCounter:
    """Running token-usage totals of sessions, kept in one Redis hash per session."""

    def __init__(self, redis_client: redis.Redis):
        self.redis_client = redis_client

    def add_once(self, message_usages: list[MessageTokenUsage]) -> None:
        """Add each message's usage to its session's total, unless it was added before.

        Idempotent per message uuid: a session's counted uuids are kept in a set next to
        its total. Reading the set, then adding to the totals and to the sets, runs as
        one optimistic transaction (WATCH on the sets, then MULTI/EXEC, retried when a
        set changed in between), so a message is never counted twice, by a redelivered
        batch or by a concurrent caller, and never marked counted without its usage
        being added. Both keys of a session that got an addition expire
        ``SESSION_TOKEN_USAGE_TTL_SECONDS`` after it.
        """
        usages_by_uuid = {usage.message_uuid: usage for usage in message_usages}
        if not usages_by_uuid:
            return
        counted_keys = sorted(
            {
                session_token_usage_counted_messages_key(usage.session_id)
                for usage in usages_by_uuid.values()
            }
        )
        with self.redis_client.pipeline(transaction=True) as pipeline:
            while True:
                try:
                    pipeline.watch(*counted_keys)
                    uncounted = self._uncounted(pipeline, list(usages_by_uuid.values()))
                    if not uncounted:
                        return
                    pipeline.multi()
                    self._queue_additions(pipeline, uncounted)
                    pipeline.execute()
                    return
                except redis.WatchError:
                    continue

    @staticmethod
    def _uncounted(
        pipeline: redis.client.Pipeline, message_usages: list[MessageTokenUsage]
    ) -> list[MessageTokenUsage]:
        # A watching pipeline runs commands at once, so these are plain reads.
        usages_by_session = defaultdict(list)
        for usage in message_usages:
            usages_by_session[usage.session_id].append(usage)

        uncounted = []
        for session_id, session_usages in usages_by_session.items():
            already_counted = pipeline.smismember(
                session_token_usage_counted_messages_key(session_id),
                [usage.message_uuid for usage in session_usages],
            )
            uncounted.extend(
                usage
                for usage, is_counted in zip(session_usages, already_counted, strict=True)
                if not is_counted
            )
        return uncounted

    @staticmethod
    def _queue_additions(
        pipeline: redis.client.Pipeline, message_usages: list[MessageTokenUsage]
    ) -> None:
        usages_by_session = defaultdict(list)
        for usage in message_usages:
            usages_by_session[usage.session_id].append(usage)

        for session_id, session_usages in usages_by_session.items():
            total_key = session_token_usage_key(session_id)
            counted_key = session_token_usage_counted_messages_key(session_id)
            for field in TOKEN_COUNT_FIELDS:
                field_total = sum(usage.token_usage[field] for usage in session_usages)
                if field_total:
                    pipeline.hincrby(total_key, field, field_total)
            cost_total = sum(usage.token_usage[COST_FIELD] for usage in session_usages)
            if cost_total:
                pipeline.hincrbyfloat(total_key, COST_FIELD, cost_total)
            pipeline.sadd(counted_key, *(usage.message_uuid for usage in session_usages))
            pipeline.expire(total_key, SESSION_TOKEN_USAGE_TTL_SECONDS)
            pipeline.expire(counted_key, SESSION_TOKEN_USAGE_TTL_SECONDS)

    def read(self, session_id: int) -> dict:
        """Return the session's total so far; zeros when nothing was added."""
        stored = self.redis_client.hgetall(session_token_usage_key(session_id))
        total_usage = empty_token_usage()
        for field in TOKEN_COUNT_FIELDS:
            total_usage[field] = int(stored.get(field, 0))
        total_usage[COST_FIELD] = float(stored.get(COST_FIELD, 0))
        return total_usage
