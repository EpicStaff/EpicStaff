from tables.graph_versioning.handlers.null_fk_handler import NullFkHandler
from tables.import_export.enums import NodeType


class AgentNodeHandler(NullFkHandler):
    node_type = NodeType.AGENT_NODE
    fk_field = "agent_definition"
    missing_set_attr = "agent_definitions"
    dependency_label = "Agent"
