TAG_MAP = [
    # Authentication
    ("api/auth/", "Authentication"),
    # Agent Definitions
    ("api/agent-definitions", "Agent Definitions"),
    # Surfaces
    ("api/surfaces", "Surfaces"),
    # Graphs
    ("api/graphs", "Graphs"),
    # Graph resources
    ("api/graph-light", "Graphs (Light)"),
    ("api/graph-versions", "Graph Versions"),
    ("api/graph-notes", "Graph Notes"),
    ("api/graph-session-messages", "Graph Session Messages"),
    # Nodes
    ("api/pythonnodes", "Python Nodes"),
    ("api/startnodes", "Start Nodes"),
    ("api/endnodes", "End Nodes"),
    ("api/subgraph-nodes", "Subgraph Nodes"),
    ("api/tasknodes", "Task Nodes"),
    ("api/agentnodes", "Agent Nodes"),
    ("api/agentnodetasks", "Agent Node Tasks"),
    ("api/file-extractor-nodes", "File Extractor Nodes"),
    ("api/audio-transcription-nodes", "Audio Transcription Nodes"),
    ("api/decision-table-node", "Decision Table Nodes"),
    ("api/classification-decision-table-node", "Classification Decision Table Nodes"),
    ("api/schedule-trigger-nodes", "Schedule Trigger Nodes"),
    ("api/knowledge-nodes", "Knowledge Nodes"),
    # Telegram
    ("api/telegram-trigger-available-fields", "Telegram"),
    ("api/telegram-trigger-nodes", "Telegram"),
    # Edges
    ("api/edges", "Edges"),
    ("api/conditionaledges", "Conditional Edges"),
    # Sessions
    ("api/sessions", "Sessions"),
    ("api/run-session", "Run Session"),
    # Providers
    ("api/providers", "Providers"),
    # LLM & Embeddings
    ("api/llm-models", "LLM Models"),
    ("api/llm-configs", "LLM Configs"),
    ("api/embedding-models", "Embedding Models"),
    ("api/embedding-configs", "Embedding Configs"),
    # Tools
    ("api/mcp-tools", "MCP Tools"),
    ("api/python-code-tool-configs", "Python Code Tool Configs"),
    ("api/python-code-tool", "Python Code Tool"),
    ("api/python-code-result", "Python Code Results"),
    ("api/run-python-code", "Run Python Code"),
    # Knowledge & RAG
    ("api/documents", "Knowledge & RAG"),
    ("api/naive-rag", "Knowledge & RAG"),
    ("api/process-rag-indexing", "Knowledge & RAG"),
    ("api/source-collections", "Knowledge & RAG"),
    ("api/graph-rag", "Graph RAG"),
    # Realtime Agents & Sessions
    ("api/realtime-agent-definitions", "Realtime Agents & Sessions"),
    ("api/realtime-agent-chats", "Realtime Agents & Sessions"),
    ("api/realtime-session-items", "Realtime Agents & Sessions"),
    ("api/init-realtime", "Realtime Agents & Sessions"),
    # Realtime Configs
    ("api/openai-realtime-configs", "Realtime Configs"),
    ("api/elevenlabs-realtime-configs", "Realtime Configs"),
    ("api/gemini-realtime-configs", "Realtime Configs"),
    # Realtime Configs (Legacy)
    ("api/realtime-transcription-model-configs", "Realtime Configs (Legacy)"),
    ("api/realtime-transcription-models", "Realtime Configs (Legacy)"),
    ("api/realtime-model-configs", "Realtime Configs (Legacy)"),
    ("api/realtime-models", "Realtime Configs (Legacy)"),
    # Realtime Channels & Voices
    ("api/realtime-channels", "Realtime Channels & Voices"),
    ("api/realtime-voices", "Realtime Channels & Voices"),
    ("api/twilio-channels", "Realtime Channels & Voices"),
    ("api/twilio", "Realtime Channels & Voices"),
    # Voice Recordings
    ("api/conversation-recordings", "Voice Recordings"),
    # Webhook Triggers
    ("api/webhook-triggers", "Webhook Triggers"),
    # Webhook Trigger Nodes
    ("api/webhook-trigger-nodes", "Webhook Trigger Nodes"),
    # Organizations
    ("api/graph-organization-users", "Graph Organization Users"),
    ("api/graph-organizations", "Graph Organizations"),
    ("api/admin/organizations", "Admin: Organizations"),
    ("api/admin/users", "Admin: Users"),
    ("api/admin/roles", "Admin: Roles"),
    # Config / Defaults
    ("api/tool-labels", "Tool Labels"),
    ("api/labels", "Labels"),
    ("api/secrets", "Secrets"),
    ("api/storage", "Storage"),
    ("api/default-", "Defaults"),
    ("api/quickstart", "Quickstart"),
]

TAGS_ORDER = [
    "Authentication",
    "Agent Definitions",
    "Surfaces",
    "Graphs",
    "Graphs (Light)",
    "Graph Versions",
    "Graph Notes",
    "Graph Session Messages",
    "Python Nodes",
    "Start Nodes",
    "End Nodes",
    "Subgraph Nodes",
    "Task Nodes",
    "Agent Nodes",
    "Agent Node Tasks",
    "File Extractor Nodes",
    "Audio Transcription Nodes",
    "Decision Table Nodes",
    "Classification Decision Table Nodes",
    "Schedule Trigger Nodes",
    "Knowledge Nodes",
    "Telegram",
    "Edges",
    "Conditional Edges",
    "Sessions",
    "Run Session",
    "Providers",
    "LLM Models",
    "LLM Configs",
    "Embedding Models",
    "Embedding Configs",
    "MCP Tools",
    "Python Code Tool",
    "Python Code Tool Configs",
    "Python Code Results",
    "Run Python Code",
    "Knowledge & RAG",
    "Graph RAG",
    "Realtime Agents & Sessions",
    "Realtime Configs",
    "Realtime Configs (Legacy)",
    "Realtime Channels & Voices",
    "Voice Recordings",
    "Webhook Triggers",
    "Webhook Trigger Nodes",
    "Graph Organizations",
    "Graph Organization Users",
    "Admin: Organizations",
    "Admin: Users",
    "Admin: Roles",
    "Tool Labels",
    "Labels",
    "Secrets",
    "Storage",
    "Defaults",
    "Quickstart",
    "Other",
]


def _get_tag(path: str) -> str:
    for fragment, tag in TAG_MAP:
        if fragment in path:
            return tag
    return "Other"


def assign_tags_postprocessing_hook(result, generator, request, public, **kwargs):
    for path, path_item in result.get("paths", {}).items():
        for operation in path_item.values():
            if isinstance(operation, dict):
                operation["tags"] = [_get_tag(path)]

    result["tags"] = [{"name": tag} for tag in TAGS_ORDER]
    return result


ORG_HEADER_SCHEME = "OrganizationId"


def add_org_header_postprocessing_hook(result, generator, request, public, **kwargs):
    components = result.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes[ORG_HEADER_SCHEME] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-Organization-Id",
        "description": (
            "Active organization context. Required by org-scoped endpoints "
            "(e.g. /api/admin/roles/). Click Authorize and paste the org UUID; "
            "Swagger will send it on every request."
        ),
    }

    for path_item in result.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            security = operation.setdefault("security", [])
            if not any(ORG_HEADER_SCHEME in entry for entry in security):
                security.append({ORG_HEADER_SCHEME: []})

    return result
