from tables.import_export.enums import NodeType
from tables.graph_versioning.handlers.null_fk_handler import NullFkHandler


class TaskNodeHandler(NullFkHandler):
    node_type = NodeType.TASK_NODE
    fk_field = "agent_definition"
    missing_set_attr = "agent_definitions"
    dependency_label = "Agent"
