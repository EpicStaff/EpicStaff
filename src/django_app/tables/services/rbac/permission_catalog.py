"""Static taxonomy for the permission matrix UI.

Single source of truth for which actions apply to which resource type.
Read by `PermissionCatalogView` (FE matrix UI) and indirectly by the
built-in role seed migration (for sanity-checking applicable bits).
"""

from tables.models.rbac_models.rbac_enums import Permission, ResourceType


# Action metadata: ordered as the FE renders the matrix columns.
ACTION_METADATA = [
    {"code": "create", "label": "Create", "bit": int(Permission.CREATE)},
    {"code": "read", "label": "View", "bit": int(Permission.READ)},
    {"code": "update", "label": "Edit", "bit": int(Permission.UPDATE)},
    {"code": "delete", "label": "Delete", "bit": int(Permission.DELETE)},
    {"code": "export", "label": "Export", "bit": int(Permission.EXPORT)},
    # TODO: Future actions:
    # {"code": "use", "label": "Use", "bit": int(Permission.USE)},
    # {"code": "list", "label": "List", "bit": int(Permission.LIST)},
]


# Resource type metadata: ordered as the FE renders the matrix rows,
# grouped by `group` (admin | workspace | config).
RESOURCE_TYPE_METADATA = [
    {
        "code": ResourceType.ORGANIZATIONS.value,
        "label": "Organizations",
        "group": "admin",
        "description": "Create, rename, deactivate organizations",
        "applicable_actions": ["create", "read", "update", "delete"],
    },
    {
        "code": ResourceType.USERS.value,
        "label": "Users",
        "group": "admin",
        "description": "Add/remove members, assign roles within org",
        "applicable_actions": ["create", "read", "update", "delete"],
    },
    {
        "code": ResourceType.ROLES.value,
        "label": "Roles",
        "group": "admin",
        "description": "Create/edit custom roles and assign to users",
        "applicable_actions": ["create", "read", "update", "delete"],
    },
    {
        "code": ResourceType.FLOWS.value,
        "label": "Flows",
        "group": "workspace",
        "description": "Workflow definitions and their nodes",
        "applicable_actions": ["create", "read", "update", "delete", "export"],
    },
    {
        "code": ResourceType.AGENTS.value,
        "label": "Agents",
        "group": "workspace",
        "description": "AI agent configurations",
        "applicable_actions": ["create", "read", "update", "delete", "export"],
    },
    {
        "code": ResourceType.TOOLS.value,
        "label": "Tools",
        "group": "workspace",
        "description": "Tool definitions and configurations",
        "applicable_actions": ["create", "read", "update", "delete"],
    },
    {
        "code": ResourceType.KNOWLEDGE_SOURCES.value,
        "label": "Knowledge Sources",
        "group": "workspace",
        "description": "RAG collections and embeddings",
        "applicable_actions": ["create", "read", "update", "delete"],
    },
    {
        "code": ResourceType.FILES.value,
        "label": "Storage (Files)",
        "group": "workspace",
        "description": "Files and folders in organization storage",
        "applicable_actions": ["create", "read", "update", "delete", "export"],
    },
    {
        "code": ResourceType.PROJECTS.value,
        "label": "Projects",
        "group": "workspace",
        "description": "Organize AI agents and tasks",
        "applicable_actions": ["create", "read", "update", "delete", "export"],
    },
    {
        "code": ResourceType.LLM_CONFIGS.value,
        "label": "LLM Configs",
        "group": "config",
        "description": "LLM model configurations and settings",
        "applicable_actions": ["create", "read", "update", "delete"],
    },
    {
        "code": ResourceType.SECRETS.value,
        "label": "API Keys / Secrets",
        "group": "config",
        "description": "Provider API keys, credentials, sensitive config",
        "applicable_actions": ["create", "read", "update", "delete"],
    },
]


def applicable_actions_for(resource_type: str) -> list[str]:
    """Return the applicable action codes for a resource_type, or []
    if the code is unknown. Used by the bitmask serialization helper
    to filter out non-applicable bits when rendering role responses."""
    for entry in RESOURCE_TYPE_METADATA:
        if entry["code"] == resource_type:
            return entry["applicable_actions"]
    return []
