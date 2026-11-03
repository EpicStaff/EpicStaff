def node_label_from_runtime_name(runtime_node_name: str) -> str:
    """Return the label the user sees for a node, "Search docs #1", from the name it runs under.

    Django names a node it sends to crew "<label> #<node id>" (`runtime_node_name` in
    django_app's `utils/graph_utils.py`), where the label is "<name> #<number>", or the bare
    name for an unnumbered node. The node id means nothing to the user, so messages drop it.
    A name without that suffix is returned unchanged.
    """
    label, separator, node_id = runtime_node_name.rpartition(" #")
    # An unnamed node runs as " #4512": with no label to show, the name is kept as it is.
    if separator and label and node_id.isdigit():
        return label
    return runtime_node_name
