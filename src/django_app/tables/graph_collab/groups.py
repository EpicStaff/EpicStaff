def graph_group_name(graph_id: int) -> str:
    """Channel-layer group for a single graph's live editors."""
    return f"graph_edit_{graph_id}"


def org_group_name(org_id: int) -> str:
    """Channel-layer group for org-wide broadcasts.

    Generic, reusable per-org broadcast primitive.
    Keep it to low-frequency "something changed, refresh" signals; never
    cursors/locks/per-node diffs.
    """
    return f"org_{org_id}"
