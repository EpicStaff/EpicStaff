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
        "description": "Rename and manage organization settings",
        # read = view the org-admin surface; update = rename/settings.
        # create (a new org) and delete (deactivate/reactivate) are platform-level.
        "applicable_actions": ["read", "update"],
        "platform_actions": ["create", "delete"],
    },
    {
        "code": ResourceType.MEMBERSHIPS.value,
        "label": "Memberships",
        "group": "admin",
        # Governs org MEMBERSHIP (add/remove/re-role members). The global user
        # ACCOUNT entity (create account, reset password, grant superadmin,
        # activate/deactivate) is a separate superadmin-only surface, not part
        # of this matrix — which is why there are no platform_actions here.
        "description": "Add, remove, and re-role members within an organization",
        "applicable_actions": ["create", "read", "update", "delete"],
        "platform_actions": [],
    },
    {
        "code": ResourceType.ROLES.value,
        "label": "Roles",
        "group": "admin",
        "description": "Create/edit custom roles and assign to users",
        "applicable_actions": ["create", "read", "update", "delete"],
        "platform_actions": [],
    },
    {
        "code": ResourceType.FLOWS.value,
        "label": "Flows",
        "group": "workspace",
        "description": "Workflow definitions and their nodes",
        "applicable_actions": ["create", "read", "update", "delete", "export"],
        "platform_actions": [],
    },
    {
        "code": ResourceType.AGENTS.value,
        "label": "Agents",
        "group": "workspace",
        "description": "AI agent configurations",
        "applicable_actions": ["create", "read", "update", "delete", "export"],
        "platform_actions": [],
    },
    {
        "code": ResourceType.TOOLS.value,
        "label": "Tools",
        "group": "workspace",
        "description": "Tool definitions and configurations",
        "applicable_actions": ["create", "read", "update", "delete"],
        "platform_actions": [],
    },
    {
        "code": ResourceType.KNOWLEDGE_SOURCES.value,
        "label": "Knowledge Sources",
        "group": "workspace",
        "description": "RAG collections and embeddings",
        "applicable_actions": ["create", "read", "update", "delete"],
        "platform_actions": [],
    },
    {
        "code": ResourceType.FILES.value,
        "label": "Storage (Files)",
        "group": "workspace",
        "description": "Files and folders in organization storage",
        "applicable_actions": ["create", "read", "update", "delete", "export"],
        "platform_actions": [],
    },
    {
        "code": ResourceType.PROJECTS.value,
        "label": "Projects",
        "group": "workspace",
        "description": "Organize AI agents and tasks",
        "applicable_actions": ["create", "read", "update", "delete", "export"],
        "platform_actions": [],
    },
    {
        "code": ResourceType.LLM_CONFIGS.value,
        "label": "LLM Configs",
        "group": "config",
        "description": "LLM model configurations and settings",
        "applicable_actions": ["create", "read", "update", "delete"],
        "platform_actions": [],
    },
    {
        "code": ResourceType.SECRETS.value,
        "label": "API Keys / Secrets",
        "group": "config",
        "description": "Provider API keys, credentials, sensitive config",
        "applicable_actions": ["create", "read", "update", "delete"],
        "platform_actions": [],
    },
]


_METADATA_BY_CODE = {entry["code"]: entry for entry in RESOURCE_TYPE_METADATA}


def applicable_actions_for(resource_type: str) -> list[str]:
    """Return the applicable action codes for a resource_type, or []
    if the code is unknown. Used by the bitmask serialization helper
    to filter out non-applicable bits when rendering role responses."""
    entry = _METADATA_BY_CODE.get(resource_type)
    return entry["applicable_actions"] if entry else []


def platform_actions_for(resource_type: str) -> list[str]:
    """Return the platform (global, superadmin-only) action codes for a
    resource_type, or [] if the code is unknown. These actions are shown in
    the catalog but are never grantable into a custom role — role validation
    rejects them."""
    entry = _METADATA_BY_CODE.get(resource_type)
    return entry.get("platform_actions", []) if entry else []
