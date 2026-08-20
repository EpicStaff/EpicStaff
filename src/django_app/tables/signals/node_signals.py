from django.db.models import Q
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from tables.models import CrewNode
from tables.models.graph_models import ConditionalEdge, Edge


def cleanup_node_edges(node):
    """Delete Edge/ConditionalEdge rows pointing at `node`.

    Edge.start_node_id/end_node_id and ConditionalEdge.source_node_id are
    plain BigIntegerFields, not ForeignKeys, so nothing cleans them up
    automatically when a node is deleted -- whether directly, via
    bulk-delete, or cascaded from a parent (e.g. Crew -> CrewNode). Must run
    as a pre_delete signal, not a perform_destroy/delete() override: Django's
    cascade collector bulk-deletes cascaded rows without calling their
    model-level delete(), but it does fire pre_delete/post_delete signals.
    """
    Edge.objects.filter(graph_id=node.graph_id).filter(
        Q(start_node_id=node.id) | Q(end_node_id=node.id)
    ).delete()
    ConditionalEdge.objects.filter(
        graph_id=node.graph_id, source_node_id=node.id
    ).delete()


@receiver(pre_delete, sender=CrewNode)
def cleanup_crew_node_edges(sender, instance, **kwargs):
    cleanup_node_edges(instance)
