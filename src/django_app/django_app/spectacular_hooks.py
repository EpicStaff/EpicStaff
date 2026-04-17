TAG_MAP = [
    ("api/auth/", "Authentication"),
    ("api/realtime-agents", "Realtime"),
    ("api/realtime-agent-chats", "Realtime"),
    ("api/realtime-models", "Realtime"),
    ("api/realtime-model-configs", "Realtime"),
    ("api/realtime-transcription", "Realtime"),
    ("api/realtime-session-items", "Realtime"),
    ("api/init-realtime", "Realtime"),
    ("api/template-agents", "Agents"),
    ("api/agents", "Agents"),
    ("api/agent-tags", "Agents"),
    ("api/crews", "Crews"),
    ("api/tasks", "Crews"),
    ("api/crew-tags", "Crews"),
    ("api/graphs", "Graphs & Nodes"),
    ("api/graph-files", "Graphs & Nodes"),
    ("api/graph-light", "Graphs & Nodes"),
    ("api/graph-tags", "Graphs & Nodes"),
    ("api/graph-session-messages", "Sessions"),
    ("api/graph-organizations", "Organizations"),
    ("api/graph-organization-users", "Organizations"),
    ("api/crewnodes", "Graphs & Nodes"),
    ("api/pythonnodes", "Graphs & Nodes"),
    ("api/llmnodes", "Graphs & Nodes"),
    ("api/startnodes", "Graphs & Nodes"),
    ("api/endnodes", "Graphs & Nodes"),
    ("api/subgraph-nodes", "Graphs & Nodes"),
    ("api/edges", "Graphs & Nodes"),
    ("api/conditionaledges", "Graphs & Nodes"),
    ("api/note-nodes", "Graphs & Nodes"),
    ("api/file-extractor-nodes", "Graphs & Nodes"),
    ("api/audio-transcription-nodes", "Graphs & Nodes"),
    ("api/decision-table-node", "Graphs & Nodes"),
    ("api/sessions", "Sessions"),
    ("api/run-session", "Sessions"),
    ("api/answer-to-llm", "Sessions"),
    ("api/llm-configs", "LLM & Models"),
    ("api/llm-models", "LLM & Models"),
    ("api/providers", "LLM & Models"),
    ("api/embedding-configs", "LLM & Models"),
    ("api/embedding-models", "LLM & Models"),
    ("api/tools", "Tools"),
    ("api/tool-configs", "Tools"),
    ("api/python-code", "Tools"),
    ("api/mcp-tools", "Tools"),
    ("api/run-python-code", "Tools"),
    ("api/naive-rag", "Knowledge & RAG"),
    ("api/source-collections", "Knowledge & RAG"),
    ("api/documents", "Knowledge & RAG"),
    ("api/process-rag-indexing", "Knowledge & RAG"),
    ("api/webhook-trigger", "Webhooks"),
    ("api/ngrok-config", "Webhooks"),
    ("api/register-webhooks", "Webhooks"),
    ("api/telegram-trigger", "Telegram"),
    ("api/register-telegram-trigger", "Telegram"),
    ("api/organizations", "Organizations"),
    ("api/organization-users", "Organizations"),
    ("api/default-", "Config & Defaults"),
    ("api/environment", "Config & Defaults"),
    ("api/quickstart", "Config & Defaults"),
    ("api/memory", "Config & Defaults"),
]

TAGS_ORDER = [
    "Authentication",
    "Sessions",
    "Agents",
    "Crews",
    "Graphs & Nodes",
    "LLM & Models",
    "Tools",
    "Knowledge & RAG",
    "Realtime",
    "Webhooks",
    "Telegram",
    "Organizations",
    "Config & Defaults",
    "Other",
]


def _get_tag(path: str) -> str:
    for fragment, tag in TAG_MAP:
        if fragment in path:
            return tag
    return "Other"


def assign_tags_postprocessing_hook(result, generator, request, public, **kwargs):
    for path, path_item in result.get("paths", {}).items():
        for method, operation in path_item.items():
            if isinstance(operation, dict):
                operation["tags"] = [_get_tag(path)]

    result["tags"] = [{"name": tag} for tag in TAGS_ORDER]
    return result
