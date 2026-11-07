"""The name a flow node runs under, and the label a user sees in it.

Django builds a session's runtime node names and crew reads the label back out of
them for its messages, so both go through this one pair.
"""

__all__ = [
    "format_runtime_node_name",
    "parse_runtime_node_label",
]

_NODE_ID_SEPARATOR = " #"


def format_runtime_node_name(label: str, node_id: int) -> str:
    """Return the name a node runs under: its label followed by " #<global node id>".

    The label is what the user sees, "<name> #<number>" or the bare name of an
    unnumbered node. The id keeps the name unique across a session's flows.
    """
    return f"{label}{_NODE_ID_SEPARATOR}{node_id}"


def parse_runtime_node_label(name: str) -> str:
    """Return the label inside a runtime node name, dropping the " #<node id>" suffix.

    The node id means nothing to the user, so messages show the label alone. A name
    without that suffix is returned unchanged.
    """
    label, separator, node_id = name.rpartition(_NODE_ID_SEPARATOR)
    # An unnamed node runs as " #4512": with no label to show, the name is kept as it is.
    if separator and label and node_id.isdigit():
        return label
    return name
