TAG_MAP = [
    ("api/auth/", "Authentication"),
    # Admin — must precede api/organizations
    ("api/admin/organizations", "Admin: Organizations"),
    ("api/admin/users", "Admin: Users"),
    # Realtime — most specific first
    ("api/realtime-transcription-model-configs", "Realtime Transcription Configs"),
    ("api/realtime-transcription-models", "Realtime Transcription Models"),
    ("api/realtime-model-configs", "Realtime Model Configs"),
    ("api/realtime-models", "Realtime Models"),
    ("api/realtime-agent-chats", "Realtime Agent Chats"),
    ("api/realtime-agents", "Realtime Agents"),
    ("api/realtime-session-items", "Realtime Session Items"),
    ("api/init-realtime", "Realtime Init"),
    ("api/voice-settings", "Voice Settings"),
    ("api/twilio", "Twilio"),
    # Agents
    ("api/template-agents", "Template Agents"),
    ("api/agent-tags", "Agent Tags"),
    ("api/code-agent-nodes", "Code Agent Nodes"),
    ("api/agents", "Agents"),
    # Crews
    ("api/crew-tags", "Crew Tags"),
    ("api/crewnodes", "Crew Nodes"),
    ("api/crews", "Crews"),
    ("api/tasks", "Tasks"),
    # Graph resources — specific before "api/graphs"
    ("api/graph-light", "Graphs (Light)"),
    ("api/graph-tags", "Graph Tags"),
    ("api/graph-versions", "Graph Versions"),
    ("api/graph-notes", "Graph Notes"),
    ("api/graph-session-messages", "Graph Session Messages"),
    ("api/graph-organization-users", "Graph Organization Users"),
    ("api/graph-organizations", "Graph Organizations"),
    ("api/graphs", "Graphs"),
    # Nodes
    ("api/pythonnodes", "Python Nodes"),
    ("api/llmnodes", "LLM Nodes"),
    ("api/startnodes", "Start Nodes"),
    ("api/endnodes", "End Nodes"),
    ("api/subgraph-nodes", "Subgraph Nodes"),
    ("api/file-extractor-nodes", "File Extractor Nodes"),
    ("api/audio-transcription-nodes", "Audio Transcription Nodes"),
    ("api/decision-table-node", "Decision Table Nodes"),
    ("api/schedule-trigger-nodes", "Schedule Trigger Nodes"),
    # Edges
    ("api/conditionaledges", "Conditional Edges"),
    ("api/edges", "Edges"),
    # Sessions
    ("api/run-session", "Run Session"),
    ("api/sessions", "Sessions"),
    ("api/answer-to-llm", "LLM Answer"),
    # LLM & Embeddings
    ("api/llm-configs", "LLM Configs"),
    ("api/llm-models", "LLM Models"),
    ("api/providers", "Providers"),
    ("api/embedding-configs", "Embedding Configs"),
    ("api/embedding-models", "Embedding Models"),
    # Tools — most specific first
    ("api/python-code-tool-config-fields", "Python Code Tool Config Fields"),
    ("api/python-code-tool-configs", "Python Code Tool Configs"),
    ("api/python-code-tool", "Python Code Tool"),
    ("api/python-code-result", "Python Code Results"),
    ("api/run-python-code", "Run Python Code"),
    ("api/python-code", "Python Code"),
    ("api/mcp-tools", "MCP Tools"),
    ("api/tool-configs", "Tool Configs"),
    ("api/tools", "Tools"),
    # Knowledge & RAG
    ("api/naive-rag", "Naive RAG"),
    ("api/graph-rag", "Graph RAG"),
    ("api/source-collections", "Source Collections"),
    ("api/documents", "Documents"),
    ("api/process-rag-indexing", "RAG Indexing"),
    # Webhooks
    ("api/webhook-trigger-nodes", "Webhook Trigger Nodes"),
    ("api/webhook-triggers", "Webhook Triggers"),
    ("api/ngrok-config", "Ngrok Config"),
    ("api/register-webhooks", "Register Webhooks"),
    # Telegram
    ("api/telegram-trigger-available-fields", "Telegram Trigger Fields"),
    ("api/telegram-trigger-node-fields", "Telegram Trigger Fields"),
    ("api/telegram-trigger-nodes", "Telegram Trigger Nodes"),
    ("api/register-telegram-trigger", "Register Telegram"),
    # Organizations (non-admin)
    ("api/organizations", "Organizations"),
    # Config / Defaults
    ("api/labels", "Labels"),
    ("api/storage", "Storage"),
    ("api/default-", "Defaults"),
    ("api/environment", "Environment"),
    ("api/quickstart", "Quickstart"),
    ("api/memory", "Memory"),
]

TAGS_ORDER = [
    "Authentication",
    "Template Agents",
    "Agents",
    "Agent Definitions",
    "Agent Tags",
    "Code Agent Nodes",
    "Crews",
    "Crew Tags",
    "Tasks",
    "Graphs",
    "Graphs (Light)",
    "Graph Versions",
    "Graph Tags",
    "Graph Notes",
    "Graph Session Messages",
    "Crew Nodes",
    "Python Nodes",
    "LLM Nodes",
    "Start Nodes",
    "End Nodes",
    "Subgraph Nodes",
    "File Extractor Nodes",
    "Audio Transcription Nodes",
    "Decision Table Nodes",
    "Schedule Trigger Nodes",
    "Edges",
    "Conditional Edges",
    "Sessions",
    "Run Session",
    "LLM Answer",
    "Providers",
    "LLM Models",
    "LLM Configs",
    "Embedding Models",
    "Embedding Configs",
    "Tools",
    "Tool Configs",
    "MCP Tools",
    "Python Code",
    "Python Code Tool",
    "Python Code Tool Configs",
    "Python Code Tool Config Fields",
    "Python Code Results",
    "Run Python Code",
    "Naive RAG",
    "Graph RAG",
    "Source Collections",
    "Documents",
    "RAG Indexing",
    "Realtime Agents",
    "Realtime Agent Chats",
    "Realtime Models",
    "Realtime Model Configs",
    "Realtime Transcription Models",
    "Realtime Transcription Configs",
    "Realtime Session Items",
    "Realtime Init",
    "Voice Settings",
    "Twilio",
    "Webhook Triggers",
    "Webhook Trigger Nodes",
    "Register Webhooks",
    "Ngrok Config",
    "Telegram Trigger Nodes",
    "Telegram Trigger Fields",
    "Register Telegram",
    "Organizations",
    "Graph Organizations",
    "Graph Organization Users",
    "Admin: Organizations",
    "Admin: Users",
    "Labels",
    "Storage",
    "Defaults",
    "Environment",
    "Quickstart",
    "Memory",
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
