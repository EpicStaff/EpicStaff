from tables.views.storage_upload_stream_view import UPLOAD_STREAM_PATH
from tables.views.transfer_import_upload_view import (
    COLLECTION_IMPORT_JOBS_ROUTE,
    FLOW_IMPORT_JOBS_ROUTE,
)

TAG_MAP = [
    # Authentication
    ("api/auth/", "Authentication"),
    ("api/profile", "Profile"),
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
    ("api/flow-assistants", "Flow Assistants"),
    ("api/flow-filter-presets", "Flow Filter Presets"),
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
    ("api/venvs", "Venvs"),
    ("api/tool-filter-presets", "Tool Filter Presets"),
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
    ("api/admin/memberships", "Admin: Memberships"),
    ("api/admin/api-keys", "Admin: API Keys"),
    ("api/permissions", "Permissions"),
    # Config / Defaults
    ("api/tool-labels", "Tool Labels"),
    ("api/agent-labels", "Agent Labels"),
    ("api/labels", "Labels"),
    ("api/secrets", "Secrets"),
    ("api/storage", "Storage"),
    ("api/recycle-bin", "Recycle Bin"),
    ("api/execution-timeout-limits", "Execution Timeout Limits"),
    ("api/default-", "Defaults"),
    ("api/quickstart", "Quickstart"),
    # Audit
    ("api/audit", "Audit"),
    # Key Value Tables
    ("api/key-value-tables", "Key Value Tables"),
    ("api/key-value-table-entries", "Key Value Tables"),
    # Internal session endpoints, whose key is `sessions`
    ("/key-value-tables/", "Key Value Tables"),
    # Plugins
    ("api/plugins", "Plugins"),
    ("api/plugin-nodes", "Plugins"),
    ("api/plugin-public", "Plugins"),
    ("api/plugin-runtime", "Plugins"),
    ("api/admin/plugins", "Plugins"),
    ("api/admin/plugin-role-permissions", "Plugins"),
    # Notifications
    ("api/notify", "Notifications"),
    # Transfer jobs
    ("api/transfer-jobs", "Transfer Jobs"),
]

TAGS_ORDER = [
    "Authentication",
    "Profile",
    "Agent Definitions",
    "Surfaces",
    "Graphs",
    "Graphs (Light)",
    "Graph Versions",
    "Graph Notes",
    "Graph Session Messages",
    "Flow Assistants",
    "Flow Filter Presets",
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
    "Venvs",
    "Tool Filter Presets",
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
    "Admin: Memberships",
    "Admin: API Keys",
    "Permissions",
    "Tool Labels",
    "Agent Labels",
    "Labels",
    "Secrets",
    "Storage",
    "Recycle Bin",
    "Execution Timeout Limits",
    "Audit",
    "Defaults",
    "Quickstart",
    "Key Value Tables",
    "Plugins",
    "Notifications",
    "Transfer Jobs",
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


_UPLOAD_STREAM_RESPONSE = {
    "type": "object",
    "required": ["status", "path", "recycle_bin_purged"],
    "properties": {
        "status": {"type": "string", "enum": ["DONE"]},
        "path": {"type": "string", "description": "The stored file, or the archive's folder."},
        "size": {"type": "integer", "description": "Bytes stored; plain files only."},
        "extracted": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Paths of the unpacked files; archives only.",
        },
        "recycle_bin_purged": {
            "type": "array",
            "description": (
                "Storage recycle bin entries purged, oldest first, to make room; "
                "empty when the upload fit or the caller may not purge."
            ),
            "items": {
                "type": "object",
                "required": ["name", "size"],
                "properties": {
                    "name": {
                        "type": "string",
                        "nullable": True,
                        "description": (
                            "Org-relative path of the entry; a folder's ends in '/'. "
                            "Null unless the caller has FILES:READ in the organization."
                        ),
                    },
                    "size": {"type": "integer", "description": "Bytes freed."},
                },
            },
        },
    },
}


def add_stream_upload_postprocessing_hook(result, generator, request, public, **kwargs):
    """Add the streaming-upload endpoint to the schema; it is raw ASGI, which the generator misses."""
    result.setdefault("paths", {})[UPLOAD_STREAM_PATH] = {
        "post": {
            "operationId": "storage_upload_stream",
            "security": [{"BearerAuth": []}, {"ApiKeyAuth": []}],
            "description": (
                "Stream one file straight into storage: the raw body is the file, "
                "proxied to object storage in bounded memory. A plain file may be at most "
                "DJANGO_MAX_STREAM_UPLOAD_FILE_SIZE (default 2gb; none = unlimited). "
                "An archive (.zip/.tar*) up to DJANGO_MAX_ARCHIVE_FILE_SIZE is unpacked "
                "into a new folder instead. Over either cap: 413 upload_too_large. "
                "Everything is also bounded by the organization storage quota: a write "
                "that doesn't fit first purges the organization's oldest storage recycle "
                "bin entries, just enough of them, and lists them in `recycle_bin_purged`; "
                "if the whole bin isn't enough, nothing is purged "
                "(413 storage_quota_exceeded). Only a user session (not an API key) "
                "holding FILES:DELETE may cause a purge; for anyone else the bin counts "
                "as used and the upload gets the 413. The purge commits with the file's "
                "row, before object storage completes the upload: if that completion "
                "then fails, the request fails but the purged entries stay purged. "
                "GET /api/storage/upload-limits/ returns the limits."
            ),
            "parameters": [
                {
                    "in": "query",
                    "name": "path",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": "Target directory, empty for the storage root.",
                },
                {
                    "in": "query",
                    "name": "filename",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": "Target file name (routes archive vs flat file).",
                },
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                },
            },
            "responses": {
                "200": {
                    "description": (
                        "Uploaded. A plain file answers `path` and `size`, an unpacked "
                        "archive `path` (its new folder) and `extracted`."
                    ),
                    "content": {"application/json": {"schema": _UPLOAD_STREAM_RESPONSE}},
                },
                "400": {"description": "Blocked extension, bad archive or missing filename."},
                "401": {"description": "Not authenticated."},
                "403": {"description": "Missing FILES:CREATE in the active organization."},
                "413": {
                    "description": (
                        "Over the file/archive size cap (upload_too_large) or the org "
                        "storage quota (storage_quota_exceeded)."
                    )
                },
            },
        }
    }
    return result


_ZIP_BODY = {
    "required": True,
    "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
}

_IMPORT_JOB_CREATED = {
    "type": "object",
    "required": ["job_id"],
    "properties": {
        "job_id": {
            "type": "string",
            "format": "uuid",
            "description": "Poll GET /api/transfer-jobs/{job_id}/ for the outcome.",
        }
    },
}

_IMPORT_JOB_DESCRIPTION = (
    "Queue a background import of a .zip export archive, streamed as the raw request body "
    "(not multipart). At most DJANGO_MAX_KNOWLEDGE_ARCHIVE_SIZE (413 archive_too_large, "
    "checked against Content-Length first, then against the bytes received). The archive's "
    "caps, version and main entity are checked before the job is created; a plain .json "
    "export goes to the synchronous import/ endpoint instead. Started by a user or a personal "
    "API key; throttled with the export jobs (transfer_job_create), and at most 3 unfinished "
    "jobs per user and 10 per organization, a user's uploads still in progress counting as "
    "unfinished jobs. Uploads share the storage uploads' slots per worker "
    "(DJANGO_UPLOAD_MAX_CONCURRENCY_PER_ORG, DJANGO_UPLOAD_MAX_CONCURRENCY). "
    "Poll GET /api/transfer-jobs/{job_id}/."
)

_FILE_NAME_PARAMETER = {
    "in": "query",
    "name": "file_name",
    "required": False,
    "schema": {"type": "string", "maxLength": 255},
    "description": "Name of the uploaded file, shown as the job's display_name.",
}


def _import_job_responses(permission: str) -> dict:
    return {
        "202": {
            "description": "Job queued.",
            "content": {"application/json": {"schema": _IMPORT_JOB_CREATED}},
        },
        "400": {
            "description": (
                "Invalid or unknown query parameter; or the archive is refused: "
                "invalid_archive (not a zip, unsafe, over a cap), use_sync_import "
                "(older than archives), invalid_file (wrong main entity)."
            )
        },
        "401": {"description": "Not authenticated."},
        "403": {
            "description": (
                f"Missing {permission} in the active organization; "
                "transfer_job_requires_user for a caller with no user (system API key, "
                "plugin service account); or the archive holds trigger nodes and the "
                "caller lacks FLOWS:USE."
            )
        },
        "413": {"description": "archive_too_large."},
        "429": {
            "description": "Throttled; too_many_jobs: the caller or the organization "
            "is at its unfinished-job limit; or org_upload_limit_reached: the organization "
            "already runs its share of uploads."
        },
        "503": {
            "description": "upload_slots_busy (with Retry-After): no upload slot freed up "
            "in time; or the storage is unreachable."
        },
    }


def add_import_job_upload_postprocessing_hook(result, generator, request, public, **kwargs):
    """Add the import-job uploads to the schema; they are raw ASGI, which the generator misses."""
    paths = result.setdefault("paths", {})
    paths[FLOW_IMPORT_JOBS_ROUTE.path] = {
        "post": {
            "operationId": "graphs_import_jobs_create",
            "security": [{"BearerAuth": []}, {"ApiKeyAuth": []}],
            "description": _IMPORT_JOB_DESCRIPTION,
            "parameters": [
                _FILE_NAME_PARAMETER,
                {
                    "in": "query",
                    "name": "preserve_uuids",
                    "required": False,
                    "schema": {"type": "boolean", "default": False},
                    "description": "Keep the flows' UUIDs from the archive.",
                },
                {
                    "in": "query",
                    "name": "replace_existing",
                    "required": False,
                    "schema": {"type": "boolean", "default": False},
                    "description": (
                        "Overwrite flows with the same UUID; requires preserve_uuids "
                        "and FLOWS:UPDATE."
                    ),
                },
                {
                    "in": "query",
                    "name": "import_labels",
                    "required": False,
                    "schema": {"type": "boolean", "default": True},
                    "description": "Import the flows' labels.",
                },
            ],
            "requestBody": _ZIP_BODY,
            "responses": _import_job_responses("FLOWS:CREATE"),
        }
    }
    paths[COLLECTION_IMPORT_JOBS_ROUTE.path] = {
        "post": {
            "operationId": "source_collections_import_jobs_create",
            "security": [{"BearerAuth": []}, {"ApiKeyAuth": []}],
            "description": _IMPORT_JOB_DESCRIPTION,
            "parameters": [_FILE_NAME_PARAMETER],
            "requestBody": _ZIP_BODY,
            "responses": _import_job_responses("KNOWLEDGE_SOURCES:CREATE"),
        }
    }
    return result
