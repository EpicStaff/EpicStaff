"""
Node metadata used by GraphStrategy to enumerate a graph's child nodes.

Node *creation* and *serialization* logic lives in the per-node strategies
(one strategy class per node type, registered in ``entity_registry``).
GraphStrategy resolves each node's strategy from the registry via
:data:`NODE_TYPE_TO_ENTITY_TYPE` and delegates to it.

This module only maps each node type to:

* the Django reverse-relation accessor on the Graph model (used for node
  export and node-name numbering), and
* the EntityType used to resolve the node's strategy from the registry.
"""

from tables.import_export.enums import NodeType, EntityType


# NodeType -> reverse-relation accessor on the Graph model.
NODE_RELATIONS: dict[str, str] = {
    NodeType.CREW_NODE: "crew_node_list",
    NodeType.SUBGRAPH_NODE: "subgraph_node_list",
    NodeType.PYTHON_NODE: "python_node_list",
    NodeType.WEBHOOK_TRIGGER_NODE: "webhook_trigger_node_list",
    NodeType.FILE_EXTRACTOR_NODE: "file_extractor_node_list",
    NodeType.AUDIO_TRANSCRIPTION_NODE: "audio_transcription_node_list",
    NodeType.START_NODE: "start_node_list",
    NodeType.DECISION_TABLE_NODE: "decision_table_node_list",
    NodeType.CLASSIFICATION_DECISION_TABLE_NODE: "classification_decision_table_node_list",
    NodeType.TELEGRAM_TRIGGER_NODE: "telegram_trigger_node_list",
    NodeType.END_NODE: "end_node",
    NodeType.NOTE_NODE: "graph_note_list",
    NodeType.CODE_AGENT_NODE: "code_agent_node_list",
    NodeType.SCHEDULE_TRIGGER_NODE: "schedule_trigger_node_list",
}


# NodeType -> EntityType, so GraphStrategy can resolve a node's strategy from
# the registry.  Node types and entity types share the same string values, so
# this is an identity mapping that simply narrows the enum.
NODE_TYPE_TO_ENTITY_TYPE: dict[str, EntityType] = {
    node_type: EntityType(node_type.value) for node_type in NODE_RELATIONS
}
