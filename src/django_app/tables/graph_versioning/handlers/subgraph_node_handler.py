from tables.graph_versioning.handlers.null_fk_handler import NullFkHandler
from tables.import_export.enums import NodeType


class SubgraphNodeHandler(NullFkHandler):
    node_type = NodeType.SUBGRAPH_NODE
    fk_field = "subgraph"
    missing_set_attr = "subgraphs"
    dependency_label = "Subflow"
