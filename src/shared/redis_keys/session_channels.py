SESSION_STATUS_CHANNEL_PATTERN = "session:update:*:status"


def session_status_channel(session_id: int) -> str:
    """Name of the Redis pub/sub channel carrying one session's status updates.

    Crew publishes every status of the session here. django_app persists them
    through a PSUBSCRIBE on ``SESSION_STATUS_CHANNEL_PATTERN``, and each SSE
    stream subscribes to the channel of its own session only, so a stream never
    receives (or parses) another session's traffic.
    """
    return f"session:update:{session_id}:status"


def session_messages_channel(session_id: int) -> str:
    """Name of the Redis pub/sub channel announcing one session's new graph messages.

    The payload is a pointer, ``{"uuid", "session_id"}``; the message itself is
    cached under ``graph:message:{session_id}:{uuid}``. SSE streams subscribe to
    the channel of their own session.
    """
    return f"session:update:{session_id}:messages"
