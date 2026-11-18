"""Choosing the sessions a filtered session export carries."""

from django.db.models import Exists, OuterRef
from rest_framework.exceptions import NotFound
from tables.exceptions import TooManySessionsToExportError
from tables.filters import filter_sessions_by_id_search
from tables.models import Graph, Session
from tables.models.graph_models import GraphSessionMessage


def select_sessions_to_export(org_id: int, filters: dict, *, limit: int) -> list[int]:
    """Return the ids of the top-level sessions of `org_id` that match `filters`.

    Args:
        filters: The validated filters of `SessionExportAllSerializer`; none at all
            selects every visible top-level session of the organization.
        limit: Most sessions one export may carry.

    Raises:
        NotFound: `graph_id` is no flow of `org_id`, or no session matches.
        TooManySessionsToExportError: More than `limit` sessions match.
    """
    if (
        "graph_id" in filters
        and not Graph.objects.filter(id=filters["graph_id"], org_id=org_id).exists()
    ):
        raise NotFound(f"Graph {filters['graph_id']} not found")

    sessions = Session.objects.visible_in_org(org_id).filter(parent_session_id=None)
    if "graph_id" in filters:
        sessions = sessions.filter(graph_id=filters["graph_id"])
    if "graph_name" in filters:
        sessions = sessions.filter(graph__name__iexact=filters["graph_name"])
    if "status" in filters:
        sessions = sessions.filter(status__in=filters["status"])
    if "created_at_after" in filters:
        sessions = sessions.filter(created_at__gte=filters["created_at_after"])
    if "created_at_before" in filters:
        sessions = sessions.filter(created_at__lte=filters["created_at_before"])
    if "finished_at_after" in filters:
        sessions = sessions.filter(finished_at__gte=filters["finished_at_after"])
    if "finished_at_before" in filters:
        sessions = sessions.filter(finished_at__lte=filters["finished_at_before"])
    if "id_search" in filters:
        sessions = filter_sessions_by_id_search(sessions, filters["id_search"])

    node_name = filters.get("node_name")
    if node_name:
        sessions = sessions.filter(graphsessionmessage__name=node_name).distinct()

    if filters.get("is_error_cause"):
        error_messages = GraphSessionMessage.objects.filter(
            session=OuterRef("pk"), message_data__message_type="error"
        )
        if node_name:
            error_messages = error_messages.filter(name=node_name)
        sessions = sessions.filter(Exists(error_messages)).distinct()

    # One past the limit tells "too many" apart without counting every match.
    session_ids = list(sessions.order_by("id").values_list("id", flat=True)[: limit + 1])
    if not session_ids:
        raise NotFound("No sessions match the given filters")
    if len(session_ids) > limit:
        raise TooManySessionsToExportError(limit)
    return session_ids
