from tables.graph_versioning.handlers.base import _MissingSets, MissingDependencyHandler
from tables.graph_versioning.handlers.crew_node_handler import CrewNodeHandler
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
from tables.import_export.enums import NodeType

HANDLER_REGISTRY: dict[NodeType, MissingDependencyHandler] = {
    h.node_type: h
    for h in (
        CrewNodeHandler(),
        SubgraphNodeHandler(),
        CodeAgentNodeHandler(),
        WebhookTriggerNodeHandler(),
        TelegramTriggerNodeHandler(),
    )
}

__all__ = [
    "HANDLER_REGISTRY",
    "_MissingSets",
    "MissingDependencyHandler",
]
