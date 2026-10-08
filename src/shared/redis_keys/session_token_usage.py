def session_token_usage_key(session_id: int) -> str:
    """Name of the Redis hash summing one session's LLM token usage.

    django_app adds the usage of every graph message it persists, and reads the hash
    when it stores the session's status, so the total covers the whole run however
    long it took. Fields: the integer token counters and ``total_cost_usd``.
    """
    return f"session:{session_id}:token_usage"


def session_token_usage_counted_messages_key(session_id: int) -> str:
    """Name of the Redis set of the message uuids already added to the session's total.

    Updated in the same transaction as ``session_token_usage_key``, so a message whose
    uuid is in the set has its usage in the total, and one that is not, has not.
    """
    return f"session:{session_id}:token_usage:counted_messages"
