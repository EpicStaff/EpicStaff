from tables.views.storage_upload_stream_view import UPLOAD_STREAM_PATH
from tables.views.transfer_import_upload_view import (
    AGENT_DEFINITION_IMPORT_JOBS_ROUTE,
    COLLECTION_IMPORT_JOBS_ROUTE,
    FLOW_IMPORT_JOBS_ROUTE,
)

from django_app.spectacular_schema import ORG_HEADER_SCHEME

TAG_MAP = [
    ("api/auth/", "Auth & Profile"),
    ("api/profile", "Auth & Profile"),
    ("api/agent-definitions", "Agents"),
    ("api/surfaces", "Agents"),
    ("api/graphs", "Flows"),
    ("api/graph-light", "Flows"),
    ("api/graph-versions", "Flows"),
    ("api/graph-notes", "Flows"),
    ("api/flow-assistants", "Flows"),
    ("api/flow-filter-presets", "Flows"),
    ("api/edges", "Flows"),
    ("api/pythonnodes", "Flow Nodes & Triggers"),
    ("api/startnodes", "Flow Nodes & Triggers"),
    ("api/endnodes", "Flow Nodes & Triggers"),
    ("api/subgraph-nodes", "Flow Nodes & Triggers"),
    ("api/tasknodes", "Flow Nodes & Triggers"),
    ("api/agentnodes", "Flow Nodes & Triggers"),
    ("api/agentnodetasks", "Flow Nodes & Triggers"),
    ("api/file-extractor-nodes", "Flow Nodes & Triggers"),
    ("api/audio-transcription-nodes", "Flow Nodes & Triggers"),
    ("api/decision-table-node", "Flow Nodes & Triggers"),
    ("api/classification-decision-table-node", "Flow Nodes & Triggers"),
    ("api/schedule-trigger-nodes", "Flow Nodes & Triggers"),
    ("api/knowledge-nodes", "Flow Nodes & Triggers"),
    ("api/telegram-trigger-available-fields", "Flow Nodes & Triggers"),
    ("api/telegram-trigger-nodes", "Flow Nodes & Triggers"),
    ("api/webhook-triggers", "Flow Nodes & Triggers"),
    ("api/webhook-trigger-nodes", "Flow Nodes & Triggers"),
    ("api/graph-session-messages", "Sessions"),
    ("api/sessions", "Sessions"),
    ("api/run-session", "Sessions"),
    ("api/providers", "Models & Configs"),
    ("api/ai-models", "Models & Configs"),
    ("api/llm-models", "Models & Configs"),
    ("api/llm-configs", "Models & Configs"),
    ("api/embedding-models", "Models & Configs"),
    ("api/embedding-configs", "Models & Configs"),
    ("api/system-one-configs", "Models & Configs"),
    ("api/execution-timeout-limits", "Models & Configs"),
    ("api/default-", "Models & Configs"),
    ("api/mcp-tools", "Tools & Code"),
    ("api/python-code-tool-configs", "Tools & Code"),
    ("api/python-code-tool", "Tools & Code"),
    ("api/python-code-result", "Tools & Code"),
    ("api/run-python-code", "Tools & Code"),
    ("api/venvs", "Tools & Code"),
    ("api/custom-libraries", "Tools & Code"),
    ("api/tool-filter-presets", "Tools & Code"),
    ("api/documents", "Knowledge"),
    ("api/naive-rag", "Knowledge"),
    ("api/process-rag-indexing", "Knowledge"),
    ("api/source-collections", "Knowledge"),
    ("api/graph-rag", "Knowledge"),
    ("api/realtime-agent-definitions", "Voice & Realtime"),
    ("api/realtime-agent-chats", "Voice & Realtime"),
    ("api/realtime-session-items", "Voice & Realtime"),
    ("api/init-realtime", "Voice & Realtime"),
    ("api/openai-realtime-configs", "Voice & Realtime"),
    ("api/elevenlabs-realtime-configs", "Voice & Realtime"),
    ("api/gemini-realtime-configs", "Voice & Realtime"),
    ("api/realtime-transcription-model-configs", "Voice & Realtime"),
    ("api/realtime-transcription-models", "Voice & Realtime"),
    ("api/realtime-model-configs", "Voice & Realtime"),
    ("api/realtime-models", "Voice & Realtime"),
    ("api/realtime-channels", "Voice & Realtime"),
    ("api/realtime-voices", "Voice & Realtime"),
    ("api/twilio-channels", "Voice & Realtime"),
    ("api/twilio", "Voice & Realtime"),
    ("api/conversation-recordings", "Voice & Realtime"),
    ("api/graph-organization-users", "Organizations & Admin"),
    ("api/graph-organizations", "Organizations & Admin"),
    ("api/admin/organizations", "Organizations & Admin"),
    ("api/admin/users", "Organizations & Admin"),
    ("api/admin/roles", "Organizations & Admin"),
    ("api/admin/memberships", "Organizations & Admin"),
    ("api/admin/api-keys", "Organizations & Admin"),
    ("api/permissions", "Organizations & Admin"),
    ("api/tool-labels", "Labels"),
    ("api/agent-labels", "Labels"),
    ("api/labels", "Labels"),
    ("api/secrets", "Secrets"),
    ("api/storage", "Storage"),
    ("api/recycle-bin", "Recycle Bin"),
    ("api/audit", "Audit"),
    ("api/quickstart", "Quickstart"),
    ("api/key-value-tables", "Key Value Tables"),
    ("api/key-value-table-entries", "Key Value Tables"),
    # Internal session endpoints, whose key is `sessions`
    ("/key-value-tables/", "Key Value Tables"),
    ("api/plugins", "Plugins"),
    ("api/plugin-nodes", "Plugins"),
    ("api/plugin-public", "Plugins"),
    ("api/plugin-gateway", "Plugins"),
    ("api/plugin-runtime", "Plugins"),
    ("api/admin/plugins", "Plugins"),
    ("api/admin/plugin-role-permissions", "Plugins"),
    ("api/notify", "Notifications"),
    ("api/transfer-jobs", "Transfer Jobs"),
    # System
    ("api/system-info", "System"),
]

TAGS_ORDER = [
    "Auth & Profile",
    "Agents",
    "Flows",
    "Flow Nodes & Triggers",
    "Sessions",
    "Models & Configs",
    "Tools & Code",
    "Knowledge",
    "Voice & Realtime",
    "Organizations & Admin",
    "Labels",
    "Secrets",
    "Storage",
    "Recycle Bin",
    "Audit",
    "Quickstart",
    "Key Value Tables",
    "Plugins",
    "Notifications",
    "Transfer Jobs",
    "System",
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
            "security": [{"BearerAuth": [], ORG_HEADER_SCHEME: []}, {"ApiKeyAuth": []}],
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
            "security": [{"BearerAuth": [], ORG_HEADER_SCHEME: []}, {"ApiKeyAuth": []}],
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
            "security": [{"BearerAuth": [], ORG_HEADER_SCHEME: []}, {"ApiKeyAuth": []}],
            "description": _IMPORT_JOB_DESCRIPTION,
            "parameters": [_FILE_NAME_PARAMETER],
            "requestBody": _ZIP_BODY,
            "responses": _import_job_responses("KNOWLEDGE_SOURCES:CREATE"),
        }
    }
    paths[AGENT_DEFINITION_IMPORT_JOBS_ROUTE.path] = {
        "post": {
            "operationId": "agent_definitions_import_jobs_create",
            "security": [{"BearerAuth": [], ORG_HEADER_SCHEME: []}, {"ApiKeyAuth": []}],
            "description": _IMPORT_JOB_DESCRIPTION,
            "parameters": [
                _FILE_NAME_PARAMETER,
                {
                    "in": "query",
                    "name": "import_labels",
                    "required": False,
                    "schema": {"type": "boolean", "default": True},
                    "description": "Import the agents' labels.",
                },
            ],
            "requestBody": _ZIP_BODY,
            "responses": _import_job_responses("AGENTS:CREATE"),
        }
    }
    return result
