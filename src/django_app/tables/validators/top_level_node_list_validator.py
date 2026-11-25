from collections.abc import Mapping
from typing import Any

from rest_framework.exceptions import ValidationError

from tables.import_export.constants import NODE_ENTITY_TYPES


def assert_no_top_level_node_lists(export_data: Mapping[str, Any]) -> None:
    """Refuse an import file holding a node list outside `Flow[].nodes`.

    Inspect shows code for review only in nodes nested in a flow, so a top-level node
    would be created with code nobody reviewed. Top-level node lists belong to the
    partial (copy-paste) format only.

    Raises:
        ValidationError: Names every non-empty top-level node list, sorted.
    """
    node_keys = sorted(key for key in NODE_ENTITY_TYPES if export_data.get(key))
    if node_keys:
        message = (
            "Node lists outside a flow are not part of an export file: "
            f"{', '.join(node_keys)}. No changes were made."
        )
        raise ValidationError({"detail": [message]})
