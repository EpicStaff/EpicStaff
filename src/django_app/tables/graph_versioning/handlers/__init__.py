from tables.graph_versioning.handlers.base import _MissingSets, MissingDependencyHandler
from tables.graph_versioning.handlers.subgraph_node_handler import SubgraphNodeHandler
from tables.graph_versioning.handlers.code_agent_node_handler import (
    CodeAgentNodeHandler,
)
from tables.graph_versioning.handlers.webhook_trigger_node_handler import (
    WebhookTriggerNodeHandler,
)
from tables.graph_versioning.handlers.telegram_trigger_node_handler import (
    TelegramTriggerNodeHandler,
)
from tables.graph_versioning.handlers.agent_node_handler import AgentNodeHandler
from tables.graph_versioning.handlers.task_node_handler import TaskNodeHandler
from tables.import_export.enums import NodeType

HANDLER_REGISTRY: dict[NodeType, MissingDependencyHandler] = {
    h.node_type: h
    for h in (
        SubgraphNodeHandler(),
        CodeAgentNodeHandler(),
        WebhookTriggerNodeHandler(),
        TelegramTriggerNodeHandler(),
        AgentNodeHandler(),
        TaskNodeHandler(),
    )
}

__all__ = [
    "HANDLER_REGISTRY",
    "_MissingSets",
    "MissingDependencyHandler",
]
