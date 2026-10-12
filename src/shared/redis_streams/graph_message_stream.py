"""Contract of the stream carrying graph session messages from crew to django_app.

Crew appends every message a running flow emits; django_app reads them through one
consumer group, persists them, and only then acknowledges and deletes each entry, so a
message survives a slow or restarting django_app (pub/sub would drop it).
"""

from .envelope import StreamEnvelope

GRAPH_MESSAGE_STREAM = "graph.messages"
GRAPH_MESSAGE_CONSUMER_GROUP = "django-graph-message-store"
GRAPH_MESSAGE_ENVELOPE_TYPE = "graph.message"

# Crew trims the stream to about this many entries unless CREW_GRAPH_MESSAGE_STREAM_MAXLEN
# overrides it; an entry trimmed before django_app stored it is lost.
DEFAULT_GRAPH_MESSAGE_STREAM_MAXLEN = 2000


def graph_message_fields(correlation_id: str, encoded_message: str) -> dict[str, str]:
    """Wrap one graph session message into the stream entry fields crew appends.

    The ``payload`` field holds the message as JSON. django_app parses it once and
    forwards that exact string to the session's SSE channel, so the envelope must not
    nest it further.

    Crew encodes each message once and hands the same string to the audit trail, so
    it is passed here already encoded rather than as a dict.

    Args:
        correlation_id: The message's ``uuid``.
        encoded_message: A ``GraphSessionMessageData``-shaped message as JSON.
    """
    return StreamEnvelope.encoded_fields(
        GRAPH_MESSAGE_ENVELOPE_TYPE, correlation_id, encoded_message
    )
