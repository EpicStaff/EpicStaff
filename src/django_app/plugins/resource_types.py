"""The kinds of org resources a plugin can install, and where each one lives.

`PluginResource.resource_type` stores these values instead of a ContentType so the
registry survives a model being renamed or moved to another app: only the mapping
below changes, never the stored rows. Do not rename a value once it has shipped.

NOTE: `PluginResource.object_id` points at a row by primary key. A data migration
that recreates the rows of a linkable model under new primary keys (copy into a new
table, re-insert after a split, ...) must rewrite the matching `PluginResource`
rows in the same migration. Otherwise every installed plugin silently loses track
of what it installed, and suspend/delete stop reaching those rows.
"""

from dataclasses import dataclass

from django.apps import apps
from django.db import models
from rbac.models.enums import ResourceType
from tables.import_export.enums import EntityType
from tables.import_export.permissions import ENTITY_RESOURCE_MAP


class PluginResourceType(models.TextChoices):
    FLOW = "flow", "Flow"
    AGENT_DEFINITION = "agent_definition", "Agent"
    SURFACE = "surface", "Surface"
    LLM_CONFIG = "llm_config", "LLM config"
    EMBEDDING_CONFIG = "embedding_config", "Embedding config"
    PYTHON_CODE_TOOL = "python_code_tool", "Python tool"
    MCP_TOOL = "mcp_tool", "MCP tool"
    WEBHOOK_TRIGGER = "webhook_trigger", "Webhook trigger"
    SECRET = "secret", "Secret"
    SOURCE_COLLECTION = "source_collection", "Knowledge collection"
    STORAGE_FILE = "storage_file", "Storage file"
    # A custom model the importer had to create because the org's catalog lacked
    # the one a bundled config names. Only rows the install created are linked.
    LLM_MODEL = "llm_model", "LLM model"
    EMBEDDING_MODEL = "embedding_model", "Embedding model"
    KEY_VALUE_TABLE = "key_value_table", "Key-value table"


@dataclass(frozen=True)
class ResourceModel:
    """Where one resource type is stored, which column names a row for people,
    and which column holds the owning organization."""

    model_label: str
    display_field: str
    org_field: str = "org"

    @property
    def model(self) -> type[models.Model]:
        return apps.get_model(self.model_label)


RESOURCE_MODELS: dict[PluginResourceType, ResourceModel] = {
    PluginResourceType.FLOW: ResourceModel("tables.Graph", "name"),
    PluginResourceType.AGENT_DEFINITION: ResourceModel(
        "agents.AgentDefinition", "name", org_field="organization"
    ),
    PluginResourceType.SURFACE: ResourceModel("agents.Surface", "name", org_field="organization"),
    PluginResourceType.LLM_CONFIG: ResourceModel("tables.LLMConfig", "custom_name"),
    PluginResourceType.EMBEDDING_CONFIG: ResourceModel("tables.EmbeddingConfig", "custom_name"),
    PluginResourceType.PYTHON_CODE_TOOL: ResourceModel("tables.PythonCodeTool", "name"),
    PluginResourceType.MCP_TOOL: ResourceModel("tables.McpTool", "name"),
    PluginResourceType.WEBHOOK_TRIGGER: ResourceModel("tables.WebhookTrigger", "path"),
    PluginResourceType.SECRET: ResourceModel("tables.Secret", "name"),
    PluginResourceType.SOURCE_COLLECTION: ResourceModel(
        "tables.SourceCollection", "collection_name"
    ),
    PluginResourceType.STORAGE_FILE: ResourceModel("tables.StorageFile", "path"),
    PluginResourceType.LLM_MODEL: ResourceModel("tables.LLMModel", "name"),
    PluginResourceType.EMBEDDING_MODEL: ResourceModel("tables.EmbeddingModel", "name"),
    PluginResourceType.KEY_VALUE_TABLE: ResourceModel("tables.KeyValueTable", "name"),
}


@dataclass(frozen=True)
class ImportedEntity:
    """How an entity list of `resources.json` becomes plugin-owned rows."""

    resource_type: PluginResourceType
    # The key naming an entry inside resources.json, used before the import exists.
    name_key: str


# Entity types of resources.json that the plugin owns. The importer force-creates
# every one of them (never reuses an org row), and only these are registered.
IMPORTED_ENTITIES: dict[EntityType, ImportedEntity] = {
    EntityType.GRAPH: ImportedEntity(PluginResourceType.FLOW, "name"),
    EntityType.AGENT_DEFINITION: ImportedEntity(PluginResourceType.AGENT_DEFINITION, "name"),
    EntityType.SURFACE: ImportedEntity(PluginResourceType.SURFACE, "name"),
    EntityType.LLM_CONFIG: ImportedEntity(PluginResourceType.LLM_CONFIG, "custom_name"),
    EntityType.EMBEDDING_CONFIG: ImportedEntity(PluginResourceType.EMBEDDING_CONFIG, "custom_name"),
    EntityType.PYTHON_CODE_TOOL: ImportedEntity(PluginResourceType.PYTHON_CODE_TOOL, "name"),
    EntityType.MCP_TOOL: ImportedEntity(PluginResourceType.MCP_TOOL, "name"),
    EntityType.WEBHOOK_TRIGGER: ImportedEntity(PluginResourceType.WEBHOOK_TRIGGER, "path"),
    # Its name is already prefixed with the plugin id when the bundle is loaded.
    EntityType.KEY_VALUE_TABLE: ImportedEntity(PluginResourceType.KEY_VALUE_TABLE, "name"),
}

PLUGIN_OWNED_TYPES: frozenset[EntityType] = frozenset(IMPORTED_ENTITIES)

# What an `access[]` entry's `type` grants the plugin page, keyed by the manifest
# value. The presenter resolves an entry's installed row through this.
ACCESS_RESOURCE_TYPES: dict[str, PluginResourceType] = {
    "flow": PluginResourceType.FLOW,
    "key_value_table": PluginResourceType.KEY_VALUE_TABLE,
}

# Catalog types the importer reuses when the org's catalog has a match and
# creates as an org-owned custom row when it does not. Only a created, org-owned
# row is linked, so delete removes it and never touches a shared catalog row.
CREATED_CATALOG_ENTITIES: dict[EntityType, PluginResourceType] = {
    EntityType.LLM_MODEL: PluginResourceType.LLM_MODEL,
    EntityType.EMBEDDING_MODEL: PluginResourceType.EMBEDDING_MODEL,
}

# The RBAC resource type that gates each kind of plugin row: install needs create
# on it and uninstall needs delete, so a `plugins:` permission never does to a row
# what the caller could not do directly. Rows the importer writes are gated as the
# importer gates them; the install service writes the other three itself.
RBAC_RESOURCE_TYPES: dict[PluginResourceType, ResourceType] = {
    **{
        imported.resource_type: ENTITY_RESOURCE_MAP[entity_type]
        for entity_type, imported in IMPORTED_ENTITIES.items()
    },
    **{
        resource_type: ENTITY_RESOURCE_MAP[entity_type]
        for entity_type, resource_type in CREATED_CATALOG_ENTITIES.items()
    },
    PluginResourceType.SECRET: ResourceType.SECRETS,
    PluginResourceType.SOURCE_COLLECTION: ResourceType.KNOWLEDGE_SOURCES,
    PluginResourceType.STORAGE_FILE: ResourceType.FILES,
}

# Shared catalog rows (models, tags) a bundle may reference. The importer still
# reuses a matching row, so the plugin never owns or registers them.
CATALOG_TYPES: frozenset[EntityType] = frozenset(
    {
        EntityType.LLM_MODEL,
        EntityType.EMBEDDING_MODEL,
        EntityType.LLM_MODEL_TAG,
        EntityType.LLM_CONFIG_TAG,
        EntityType.EMBEDDING_MODEL_TAG,
        EntityType.GRAPH_TAG,
        # Skipped by the importer: plugin installs never import labels.
        EntityType.LABEL,
    }
)
