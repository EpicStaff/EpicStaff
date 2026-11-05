"""Marks a write-method handler that changes nothing, so the fallback never records it.

A POST that only reads (an estimate, an export, a lookup by a list of ids too long for a
query string) looks like a change to the middleware. Marking it where it is declared keeps
the decision next to the code, inherited by every view that mixes the handler in.
`test_every_write_route_is_classified` fails for a new write route that is neither
marked nor listed as a change.

A handler marked `not_a_user_change` does write, but only a run's own state: the session
audit, not the user-action trail, covers it.
"""

READS_ONLY_ATTRIBUTE = "user_audit_reads_only"


def reads_only(handler):
    """Mark a view handler (a DRF action, or an APIView's `post`) that writes nothing."""
    setattr(handler, READS_ONLY_ATTRIBUTE, True)
    return handler


def not_a_user_change(handler):
    """Mark a view handler whose writes are a run's own state (a session started or stopped,
    an assistant chat message, the end of a voice call), so the fallback never records it."""
    return reads_only(handler)


def handler_reads_only(view_class, handler_name: str | None) -> bool:
    """Whether `view_class` serves `handler_name` (its DRF action or method name) with a
    handler marked by `reads_only`."""
    handler = getattr(view_class, handler_name, None) if handler_name else None
    return getattr(handler, READS_ONLY_ATTRIBUTE, False)
