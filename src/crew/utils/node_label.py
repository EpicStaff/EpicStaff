import re

# Django's `runtime_node_name` appends exactly one " #<node id>" to the label.
_RUNTIME_NODE_ID_SUFFIX = re.compile(r" #\d+\Z")


def runtime_node_name_to_label(node_name: str) -> str:
    """Return the label the user gave a node: "Writer #1 #352" becomes "Writer #1".

    Same rule as the frontend `runtimeNodeNameToLabel`; a name without the id suffix comes
    back unchanged. Display only: the runtime name stays the node's key, since two
    nodes can share a label.
    """
    return _RUNTIME_NODE_ID_SUFFIX.sub("", node_name)
