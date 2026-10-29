"""What a purge deletes before the root itself, in bounded batches."""

from django.db import router
from django.db.models.deletion import Collector
from tables.models import Graph
from tables.models.session_models import Session
from tables.services.cascade_org_guard import CascadeOrgGuard

SESSION_PURGE_BATCH_SIZE = 200
# Enough for the pre_delete receiver (its status) and the cascade (the pk); the JSON
# columns of a long-running flow's sessions are never loaded.
_SESSION_DELETE_FIELDS = ("pk", "status")


def delete_flow_sessions(graph: Graph) -> None:
    """Delete a binned flow's sessions, their sub-sessions and what cascades from them.

    A session follows its flow into the bin, so a flow with many runs still has all
    of them at purge time. Left to the purge's own cascade, every session would be
    loaded at once, JSON columns included, since Session's pre_delete receiver rules
    out a fast delete. Here they go `SESSION_PURGE_BATCH_SIZE` at a time through the
    same Collector, so that receiver still schedules stop_session for a session that
    is still open, and each batch is checked against the flow's organization.

    Runs in the purge's transaction, which takes the flow's lock first: a flow
    restored meanwhile is left alone, and its purge then refuses.

    Raises:
        CrossOrgCascadeError: A batch would delete or update another organization's
            row; the caller's transaction must roll back.
    """
    using = router.db_for_write(Graph, instance=graph)
    is_binned = (
        Graph.all_objects.using(using)
        .select_for_update()
        .filter(pk=graph.pk, active=False)
        .exists()
    )
    if not is_binned:
        return
    guard = CascadeOrgGuard.for_root(graph, using)
    sessions = Session.objects.using(using).filter(graph_id=graph.pk)
    while True:
        batch_pks = list(
            sessions.order_by("pk").values_list("pk", flat=True)[:SESSION_PURGE_BATCH_SIZE]
        )
        if not batch_pks:
            return
        rows = Session.objects.using(using).filter(pk__in=batch_pks).only(*_SESSION_DELETE_FIELDS)
        collector = Collector(using=using, origin=rows)
        collector.collect(rows)
        guard.check_collected(collector)
        collector.delete()
