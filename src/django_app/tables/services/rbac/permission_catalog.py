"""Static taxonomy for the permission matrix UI.

Single source of truth for which actions apply to which resource type.
Read by `PermissionCatalogView` (FE matrix UI) and indirectly by the
built-in role seed migration (for sanity-checking applicable bits).
"""

from tables.models.rbac_models.rbac_enums import Permission, ResourceType


# Action metadata: ordered as the FE renders the matrix columns. View leads —
# it is the permission every other one builds on, not bit order.
ACTION_METADATA = [
    {"code": "read", "label": "View", "bit": int(Permission.READ)},
    {"code": "create", "label": "Create", "bit": int(Permission.CREATE)},
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


# Permissions worth granting alongside another, keyed by the permission that
# triggers the suggestion. Advisory only — nothing here is enforced; the matrix
# UI uses it to nudge the author toward a coherent role.
#
# Reading a resource pulls in whatever that resource references. Creating or
# editing one needs at least the context reading it needs (enforced by test).
# Deleting and exporting need only the resource itself.
RECOMMENDED_WITH: dict[str, dict[str, tuple[tuple[str, str], ...]]] = {
    ResourceType.ORGANIZATIONS.value: {
        "read": (("memberships", "read"), ("roles", "read")),
        "update": (
            ("organizations", "read"),
            ("memberships", "read"),
            ("roles", "read"),
        ),
    },
    ResourceType.MEMBERSHIPS.value: {
        "create": (("memberships", "read"), ("roles", "read")),
        "update": (("memberships", "read"), ("roles", "read")),
        "delete": (("memberships", "read"),),
    },
    ResourceType.ROLES.value: {
        "create": (("roles", "read"),),
        "update": (("roles", "read"),),
        "delete": (("roles", "read"),),
    },
    ResourceType.FLOWS.value: {
        "read": (("projects", "read"), ("llm_configs", "read")),
        "create": (("flows", "read"), ("projects", "read"), ("llm_configs", "read")),
        "update": (("flows", "read"), ("projects", "read"), ("llm_configs", "read")),
        "delete": (("flows", "read"),),
        "export": (("flows", "read"),),
    },
    ResourceType.AGENTS.value: {
        "read": (
            ("knowledge_sources", "read"),
            ("tools", "read"),
            ("llm_configs", "read"),
        ),
        "create": (
            ("agents", "read"),
            ("knowledge_sources", "read"),
            ("tools", "read"),
            ("llm_configs", "read"),
        ),
        "update": (
            ("agents", "read"),
            ("knowledge_sources", "read"),
            ("tools", "read"),
            ("llm_configs", "read"),
        ),
        "delete": (("agents", "read"),),
        "export": (("agents", "read"),),
    },
    ResourceType.TOOLS.value: {
        "create": (("tools", "read"),),
        "update": (("tools", "read"),),
        "delete": (("tools", "read"),),
    },
    ResourceType.KNOWLEDGE_SOURCES.value: {
        "create": (("knowledge_sources", "read"), ("llm_configs", "read")),
        "update": (("knowledge_sources", "read"), ("llm_configs", "read")),
        "delete": (("knowledge_sources", "read"),),
    },
    ResourceType.FILES.value: {
        "create": (("files", "read"),),
        "update": (("files", "read"),),
        "delete": (("files", "read"),),
        "export": (("files", "read"),),
    },
    ResourceType.PROJECTS.value: {
        "create": (("projects", "read"), ("flows", "create"), ("flows", "update")),
        "update": (("projects", "read"), ("flows", "create"), ("flows", "update")),
        "delete": (("projects", "read"),),
        "export": (("projects", "read"),),
    },
    ResourceType.LLM_CONFIGS.value: {
        "create": (("llm_configs", "read"),),
        "update": (("llm_configs", "read"),),
        "delete": (("llm_configs", "read"),),
    },
    ResourceType.SECRETS.value: {
        "create": (("secrets", "read"),),
        "update": (("secrets", "read"),),
        "delete": (("secrets", "read"),),
    },
}


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


def recommended_with_for(resource_type: str) -> dict[str, list[dict]]:
    """Wire-shaped recommendations for a resource_type, keyed by action.

    Every applicable action is a key — empty list when nothing is recommended —
    so a client can index without nil-checks, matching the contract the rest of
    the catalog offers. Unknown resource types yield {}."""
    entry = _METADATA_BY_CODE.get(resource_type)
    if entry is None:
        return {}
    by_action = RECOMMENDED_WITH.get(resource_type, {})
    return {
        action: [
            {"resource_type": target, "action": target_action}
            for target, target_action in by_action.get(action, ())
        ]
        for action in entry["applicable_actions"]
    }


def build_catalog() -> dict:
    """The full `GET /api/permissions/catalog/` payload.

    Composes recommendations into fresh per-resource dicts; RESOURCE_TYPE_METADATA
    is module-level state read elsewhere and must not be mutated."""
    return {
        "actions": ACTION_METADATA,
        "resource_types": [
            {**entry, "recommended_with": recommended_with_for(entry["code"])}
            for entry in RESOURCE_TYPE_METADATA
        ],
    }
