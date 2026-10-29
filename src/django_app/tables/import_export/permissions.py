"""Maps import EntityType -> RBAC ResourceType for per-resource CREATE checks.

Every importable entity type that creates a top-level row must be listed, mapped
to the same ResourceType its API ViewSet gates on; a type absent from the map is
created on import without any permission check. Unlisted on purpose: SESSION
(not importable) and graph node types (created as children of a flow, which is
gated as FLOWS), and AUDIT_FILTER_PRESET (a personal saved search over audit data;
an entry with the same search as the importer's own preset or any shared preset in
their org is reused, otherwise a private preset is created for the importer with copy
numbering; no role holds CREATE on AUDIT, and its own import endpoint is gated on
AUDIT read). Tags map to their parent resource; models and provider realtime
configs map to LLM_CONFIGS.
"""

from rbac.access.effective import EffectivePermissions
from rbac.access.resolver import PermissionResolver
from rbac.models.enums import Permission, ResourceType

from tables.import_export.enums import EntityType

ENTITY_RESOURCE_MAP: dict[EntityType, ResourceType] = {
    EntityType.AGENT: ResourceType.AGENTS,
    EntityType.AGENT_TAG: ResourceType.AGENTS,
    EntityType.AGENT_DEFINITION: ResourceType.AGENTS,
    EntityType.SURFACE: ResourceType.SURFACES,
    EntityType.CREW: ResourceType.PROJECTS,
    EntityType.CREW_TAG: ResourceType.PROJECTS,
    EntityType.GRAPH: ResourceType.FLOWS,
    EntityType.GRAPH_TAG: ResourceType.FLOWS,
    EntityType.WEBHOOK_TRIGGER: ResourceType.WEBHOOKS,
    EntityType.LABEL: ResourceType.FLOWS,
    EntityType.LLM_CONFIG: ResourceType.LLM_CONFIGS,
    EntityType.EMBEDDING_CONFIG: ResourceType.LLM_CONFIGS,
    EntityType.REALTIME_CONFIG: ResourceType.LLM_CONFIGS,
    EntityType.REALTIME_TRANSCRIPTION_CONFIG: ResourceType.LLM_CONFIGS,
    EntityType.OPENAI_REALTIME_CONFIG: ResourceType.LLM_CONFIGS,
    EntityType.ELEVENLABS_REALTIME_CONFIG: ResourceType.LLM_CONFIGS,
    EntityType.GEMINI_REALTIME_CONFIG: ResourceType.LLM_CONFIGS,
    EntityType.LLM_MODEL: ResourceType.LLM_CONFIGS,
    EntityType.EMBEDDING_MODEL: ResourceType.LLM_CONFIGS,
    EntityType.REALTIME_MODEL: ResourceType.LLM_CONFIGS,
    EntityType.REALTIME_TRANSCRIPTION_MODEL: ResourceType.LLM_CONFIGS,
    EntityType.LLM_CONFIG_TAG: ResourceType.LLM_CONFIGS,
    EntityType.LLM_MODEL_TAG: ResourceType.LLM_CONFIGS,
    EntityType.EMBEDDING_MODEL_TAG: ResourceType.LLM_CONFIGS,
    EntityType.VENV: ResourceType.VENVS,
    EntityType.PYTHON_CODE_TOOL: ResourceType.TOOLS,
    EntityType.MCP_TOOL: ResourceType.TOOLS,
}

# Dependencies a flow or tool export bundles only when the caller may export
# their resource. Only resources with a grantable `export` bit can be listed.
EXPORT_RESOURCE_MAP: dict[EntityType, ResourceType] = {
    EntityType.AGENT_DEFINITION: ResourceType.AGENTS,
    EntityType.PYTHON_CODE_TOOL: ResourceType.TOOLS,
    EntityType.MCP_TOOL: ResourceType.TOOLS,
    # A subgraph reference is gated like any other dependency (uniform rule); the
    # flow endpoints already require flows EXPORT, so the endpoints never deny it.
    EntityType.GRAPH: ResourceType.FLOWS,
}

# Every other ENTITY_RESOURCE_MAP type is always bundled: its resource has no
# grantable `export` bit (surfaces, llm configs, webhooks), or it is a label/tag
# that only decorates the exported entity. A new type must land in one of the
# two collections; test_export_permission_entity_coverage enforces it.
EXPORT_EXEMPT_TYPES: frozenset[EntityType] = frozenset(
    {
        EntityType.AGENT,
        EntityType.AGENT_TAG,
        EntityType.SURFACE,
        EntityType.CREW,
        EntityType.CREW_TAG,
        EntityType.GRAPH_TAG,
        EntityType.WEBHOOK_TRIGGER,
        EntityType.LABEL,
        EntityType.LLM_CONFIG,
        EntityType.EMBEDDING_CONFIG,
        EntityType.REALTIME_CONFIG,
        EntityType.REALTIME_TRANSCRIPTION_CONFIG,
        EntityType.OPENAI_REALTIME_CONFIG,
        EntityType.ELEVENLABS_REALTIME_CONFIG,
        EntityType.GEMINI_REALTIME_CONFIG,
        EntityType.LLM_MODEL,
        EntityType.EMBEDDING_MODEL,
        EntityType.REALTIME_MODEL,
        EntityType.REALTIME_TRANSCRIPTION_MODEL,
        EntityType.LLM_CONFIG_TAG,
        EntityType.LLM_MODEL_TAG,
        EntityType.EMBEDDING_MODEL_TAG,
    }
)


class ExportAccessPolicy:
    """Decides which dependency types an export may bundle for one caller."""

    def __init__(self, effective_permissions: EffectivePermissions):
        self._effective_permissions = effective_permissions

    @classmethod
    def for_user(cls, user, org_id: int | None) -> "ExportAccessPolicy":
        """Build the policy from `user`'s effective permissions in the organization."""
        return cls(PermissionResolver().resolve(user=user, org_id=org_id))

    def allows(self, entity_type: EntityType) -> bool:
        """Whether a dependency of this type may be bundled into an export."""
        resource = EXPORT_RESOURCE_MAP.get(entity_type)
        if resource is None:
            return True
        return self._effective_permissions.can(resource, Permission.EXPORT)

    def can_reveal_names(self, entity_type: EntityType) -> bool:
        """Whether the caller may see the names of excluded entities of this type."""
        resource = EXPORT_RESOURCE_MAP.get(entity_type)
        if resource is None:
            return True
        return self._effective_permissions.can(resource, Permission.READ)
