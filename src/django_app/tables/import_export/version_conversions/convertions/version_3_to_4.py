from tables.import_export.enums import EntityType
from tables.import_export.version_conversions.base import VersionConverter
from tables.utils.legacy_node_number import move_legacy_badge_into_node_number


@VersionConverter.register(from_version=3)
def v3_to_v4(data: dict) -> dict:
    """
    v3 → v4:
    - A node's "#N" badge moves from its name suffix and metadata["nodeNumber"]
      into node_number. Nodes that already carry node_number (version snapshots
      rewritten by the backfill migration still say version 3) are left as they are.
    """
    for graph in data.get(EntityType.GRAPH, []):
        for node in graph.get("nodes", []):
            move_legacy_badge_into_node_number(node)
    return data
