from __future__ import annotations

# Mapping of (display_label, graph related_name) for node counting in the
# system prompt.  Each entry corresponds to a related manager on the Graph
# model.  Order is preserved in the prompt output.
NODE_RELATED_NAMES: tuple[tuple[str, str], ...] = (
    ("crew", "crew_node_list"),
    ("python", "python_node_list"),
    ("file_extractor", "file_extractor_node_list"),
    ("audio_transcription", "audio_transcription_node_list"),
    ("subgraph", "subgraph_node_list"),
    ("code_agent", "code_agent_node_list"),
    ("start", "start_node_list"),
    ("end", "end_node"),
    ("decision_table", "decision_table_node_list"),
    ("classification_decision_table", "classification_decision_table_node_list"),
    ("webhook_trigger", "webhook_trigger_node_list"),
    ("telegram_trigger", "telegram_trigger_node_list"),
)
