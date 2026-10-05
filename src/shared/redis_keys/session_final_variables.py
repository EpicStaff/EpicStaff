SESSION_FINAL_VARIABLES_TTL_SECONDS = 900


def session_final_variables_key(session_id: int) -> str:
    """Name of the Redis key holding one session's final variables as JSON.

    Crew writes it before publishing the ``end`` status, so the status message
    stays small; django_app reads it when it persists the ``end`` status and
    when it forwards that status to SSE clients. The key is never deleted: it
    expires after ``SESSION_FINAL_VARIABLES_TTL_SECONDS``, which lets every
    reader of the same ``end`` status find it.
    """
    return f"session:{session_id}:final_variables"
