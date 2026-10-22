from django.apps import apps
from django.db import transaction
from django.db.models import F, Max, Value
from django.db.models.functions import Greatest
from tables.models import Graph
from tables.utils.legacy_node_number import badge_number_or_none
from utils.singleton_meta import SingletonMeta


class NodeNumberService(metaclass=SingletonMeta):
    """Issues graph-scoped "#N" badge numbers from `Graph.node_number_seq`.

    The counter moves up only, except when an import replaces the graph's content
    (`rewind_to_surviving_nodes`), so between such rebuilds a number is never issued
    twice in a graph, even after the node that held it is deleted. The UPDATE row-locks the graph until
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

    def rewind_to_surviving_nodes(self, graph_id: int) -> None:
        """Rewind the counter of a rebuilt graph to the highest number its rows still hold.

        Called after the graph's content was wiped, so the rebuilt nodes are numbered
        right above what survives (from 1 when nothing does). Rows the wipe does not
        remove, such as legacy CrewNodes and soft-deleted nodes, keep their numbers,
        and no number they hold is issued again.
        """
        surviving_numbers = (
            model._base_manager.filter(graph_id=graph_id)
            .aggregate(highest=Max("node_number"))
            .get("highest")
            for model in _numbered_node_models()
        )
        highest_surviving = max((number for number in surviving_numbers if number), default=0)
        Graph.all_objects.filter(pk=graph_id).update(node_number_seq=highest_surviving)

    def keepable_numbers(self, graph_id: int, stored_numbers: list[object]) -> list[int | None]:
        """Decide which stored numbers the nodes of a rebuilt graph may keep.

        Called after the graph's content was wiped. A stored number is kept when it is
        a usable badge number, no row of the graph still holds it (legacy CrewNodes and
        soft-deleted nodes survive the wipe), and no earlier entry kept it already.
        Issues one query per numbered node model.

        Args:
            stored_numbers: The nodes' stored numbers, in the order they are created;
                on a duplicate the first entry wins.

        Returns:
            One entry per stored number: the number to keep, or None where the node
            must be numbered from the counter instead.
        """
        taken_numbers = self._held_numbers(graph_id)
        kept_numbers = []
        for stored_number in stored_numbers:
            number = badge_number_or_none(stored_number)
            if number is None or number in taken_numbers:
                kept_numbers.append(None)
                continue
            taken_numbers.add(number)
            kept_numbers.append(number)
        return kept_numbers

    @staticmethod
    def _held_numbers(graph_id: int) -> set[int]:
        held_numbers = set()
        for model in _numbered_node_models():
            held_numbers.update(
                model._base_manager.filter(
                    graph_id=graph_id, node_number__isnull=False
                ).values_list("node_number", flat=True)
            )
        return held_numbers


def _numbered_node_models() -> list[type]:
    from tables.models.base_models import NumberedNode

    return [model for model in apps.get_models() if issubclass(model, NumberedNode)]


def source_order_key(number: object, tiebreak: object) -> tuple[bool, int, int]:
    """Sort key for a node of a graph being rebuilt: by source number, then by `tiebreak`.

    Nodes without a source number go last. The values can come from an import file,
    so anything that is not an int (bool included) counts as absent instead of
    raising TypeError in the sort.

    Args:
        tiebreak: The node's source id; orders equal numbers and the unnumbered nodes.
    """
    number = _int_or_none(number)
    return number is None, number or 0, _int_or_none(tiebreak) or 0


def _int_or_none(value: object) -> int | None:
    # Exact type match: bool is a subclass of int.
    return value if type(value) is int else None


def source_order(numbers_by_node_id: dict[int, int | None]) -> dict[int, int]:
    """Renumber 1..K keeping the source order: #1, #4, #5 -> 1, 2, 3.

    Ordered by `source_order_key`, the same rule an import uses.
    """
    ordered_node_ids = sorted(
        numbers_by_node_id,
        key=lambda node_id: source_order_key(numbers_by_node_id[node_id], node_id),
    )
    return {node_id: position for position, node_id in enumerate(ordered_node_ids, start=1)}
