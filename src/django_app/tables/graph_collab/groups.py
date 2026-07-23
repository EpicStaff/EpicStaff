def graph_group_name(graph_id: int) -> str:
    """Channel-layer group for a single graph's live editors."""
    return f"graph_edit_{graph_id}"


def org_group_name(org_id: int) -> str:
    """Channel-layer group for org-wide broadcasts."""
    return f"org_{org_id}"
