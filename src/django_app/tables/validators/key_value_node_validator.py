from collections.abc import Iterable

from utils.graph_utils import node_label, node_list_phrase

from tables.exceptions import KeyValueNodeRunValidationError
from tables.models import KeyValueNode


class KeyValueNodeValidator:
    def validate_runnable(
        self, node_list: Iterable[KeyValueNode], *, flow_name: str | None = None
    ) -> None:
        """Refuse the run when a Key-Value node has no table, naming every such node.

        Saving one is allowed: deleting a table leaves its nodes with none selected.

        Args:
            flow_name: The subflow's name, named in the message; None for the flow that was run.

        Raises:
            KeyValueNodeRunValidationError: At least one node has no table selected.
        """
        labels = [
            node_label(node_name=node.node_name, node_number=node.node_number)
            for node in node_list
            if node.key_value_table_id is None
        ]
        if not labels:
            return
        verb = "has" if len(labels) == 1 else "have"
        raise KeyValueNodeRunValidationError(
            f"{node_list_phrase('Key-Value', labels, flow_name)} {verb} no table selected."
        )
