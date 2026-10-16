from collections.abc import Hashable

from django.apps import apps
from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Greatest
from tables.models import Graph
from utils.singleton_meta import SingletonMeta


class NodeNumberService(metaclass=SingletonMeta):
    """Issues graph-scoped "#N" badge numbers from `Graph.node_number_seq`.

    The counter only ever moves up, so a number is never issued twice in a graph,
    even after the node that held it is deleted. The UPDATE row-locks the graph until
    the surrounding transaction ends, so concurrent callers are serialised without a
    separate `select_for_update`.
    """

    def reserve(self, graph_id: int, count: int = 1) -> range:
        """Reserve `count` consecutive numbers, all above every number issued before."""
        if count < 1:
            return range(0)
        with transaction.atomic():
            graphs = Graph.all_objects.filter(pk=graph_id)
            graphs.update(node_number_seq=F("node_number_seq") + count)
            high_water_mark = graphs.values_list("node_number_seq", flat=True).get()
        return range(high_water_mark - count + 1, high_water_mark + 1)

    def raise_to(self, graph_id: int, number: int) -> None:
        """Make sure the counter is at least `number`, so a supplied number is never re-issued."""
        Graph.all_objects.filter(pk=graph_id).update(
            node_number_seq=Greatest(F("node_number_seq"), Value(number))
        )

    def restart(self, graph_id: int) -> None:
        """Reset the counter of a graph whose content is about to be rebuilt.

        Reusing numbers is only safe when nothing holds one, so soft-deleted nodes
        count as holding theirs.

        Raises:
            ValueError: The graph still has a node of any numbered type.
        """
        if any(
            model._base_manager.filter(graph_id=graph_id).exists()
            for model in _numbered_node_models()
        ):
            raise ValueError("Cannot restart node numbering while the graph still has nodes")
        Graph.all_objects.filter(pk=graph_id).update(node_number_seq=0)


def _numbered_node_models() -> list[type]:
    from tables.models.base_models import NumberedNode

    return [model for model in apps.get_models() if issubclass(model, NumberedNode)]


def source_order(numbers_by_key: dict[Hashable, int | None]) -> dict[Hashable, int]:
    """Renumber 1..K keeping the source order: #1, #4, #5 -> 1, 2, 3.

    Keys without a source number go last. Ties, and the unnumbered keys among
    themselves, are ordered by key so the result is deterministic; this requires
    the keys to be mutually sortable.
    """
    ordered_keys = sorted(
        numbers_by_key,
        key=lambda key: (numbers_by_key[key] is None, numbers_by_key[key] or 0, key),
    )
    return {key: position for position, key in enumerate(ordered_keys, start=1)}
