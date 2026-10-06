"""Where a secret slot's value will be sent, for the install review and the secrets dialog.

A bundled config or MCP tool can point at any host, so an admin must see the host
before typing a key into a slot. Each destination is
`{"resource_type", "name", "provider", "host"}`; `host` is null when the provider's
standard endpoint is used.
"""

from collections import defaultdict
from collections.abc import Callable, Collection
from dataclasses import dataclass
from urllib.parse import urlsplit

from django.db.models import Model, Q
from tables.import_export.enums import EntityType
from tables.models import EmbeddingConfig, LLMConfig, McpTool

from plugins.manifest import SECRET_BINDING_FIELDS, PluginPackage
from plugins.models import Plugin, PluginResource
from plugins.resource_types import IMPORTED_ENTITIES, PluginResourceType

_T = PluginResourceType

# The order destinations are listed in, within one slot.
_DESTINATION_ORDER = {_T.LLM_CONFIG: 0, _T.EMBEDDING_CONFIG: 1, _T.MCP_TOOL: 2}


def endpoint_host(*urls: str | None) -> str | None:
    """Hostname of the first non-blank URL; None when all are blank (the provider's standard endpoint).

    A URL without a scheme still names its host. A non-blank URL whose host cannot
    be read is returned as written, so a custom endpoint is never shown as the
    standard one.
    """
    for url in urls:
        value = (url or "").strip()
        if not value:
            continue
        try:
            parsed = urlsplit(value)
            if not parsed.netloc:
                parsed = urlsplit(f"//{value}")
            host = parsed.hostname
        except ValueError:
            host = None
        return host or value
    return None


def _destination(
    resource_type: PluginResourceType, name: str | None, provider: str | None, host: str | None
) -> dict:
    return {"resource_type": resource_type.value, "name": name, "provider": provider, "host": host}


# --- from the plugin file (install review) ------------------------------------------


def bundle_destinations(package: PluginPackage) -> dict[str, list[dict]]:
    """Slot name -> where its value will be sent, read from resources.json and the bindings only.

    The importer reuses a catalog model only when every field matches, `base_url`
    included, so the bundle's model `base_url` is the one the installed config uses.
    """
    entities_by_type = {
        entity_type: {entity["id"]: entity for entity in package.entities(entity_type)}
        for entity_type in (
            EntityType.LLM_CONFIG,
            EntityType.LLM_MODEL,
            EntityType.EMBEDDING_CONFIG,
            EntityType.EMBEDDING_MODEL,
            EntityType.MCP_TOOL,
        )
    }
    destinations: dict[str, list[dict]] = defaultdict(list)
    for binding in package.manifest.secret_bindings:
        entity = entities_by_type[EntityType(binding.entity)][binding.ref]
        destinations[binding.slot].append(
            _BUNDLE_DESTINATIONS[EntityType(binding.entity)](entity, entities_by_type)
        )
    return {
        slot: sorted(items, key=lambda item: _DESTINATION_ORDER[_T(item["resource_type"])])
        for slot, items in destinations.items()
    }


def _bundle_llm_config(config: dict, entities_by_type: dict) -> dict:
    model = entities_by_type[EntityType.LLM_MODEL].get(config.get("model")) or {}
    return _destination(
        _T.LLM_CONFIG,
        config.get("custom_name"),
        model.get("provider_name"),
        _llm_host(model.get("base_url"), config.get("base_url")),
    )


def _bundle_embedding_config(config: dict, entities_by_type: dict) -> dict:
    model = entities_by_type[EntityType.EMBEDDING_MODEL].get(config.get("model")) or {}
    return _destination(
        _T.EMBEDDING_CONFIG,
        config.get("custom_name"),
        model.get("provider_name"),
        endpoint_host(model.get("base_url")),
    )


def _bundle_mcp_tool(tool: dict, entities_by_type: dict) -> dict:
    return _destination(_T.MCP_TOOL, tool.get("name"), None, endpoint_host(tool.get("transport")))


_BUNDLE_DESTINATIONS: dict[EntityType, Callable[[dict, dict], dict]] = {
    EntityType.LLM_CONFIG: _bundle_llm_config,
    EntityType.EMBEDDING_CONFIG: _bundle_embedding_config,
    EntityType.MCP_TOOL: _bundle_mcp_tool,
}


def _llm_host(model_base_url: str | None, config_base_url: str | None) -> str | None:
    # Requests go to the model's base_url (ConverterService.convert_llm_config_to_pydantic).
    # The config's own base_url is not read at run time today; it is reported when it
    # is the only one set, so a plugin cannot park an endpoint there unseen.
    return endpoint_host(model_base_url, config_base_url)


# --- from the installed rows (plugin detail, secrets dialog) -------------------------


def _installed_llm_config(config: LLMConfig) -> dict:
    model = config.model
    return _destination(
        _T.LLM_CONFIG,
        config.custom_name,
        model.llm_provider.name if model and model.llm_provider else None,
        _llm_host(model.base_url if model else None, config.base_url),
    )


def _installed_embedding_config(config: EmbeddingConfig) -> dict:
    model = config.model
    return _destination(
        _T.EMBEDDING_CONFIG,
        config.custom_name,
        model.embedding_provider.name if model and model.embedding_provider else None,
        endpoint_host(model.base_url if model else None),
    )


def _installed_mcp_tool(tool: McpTool) -> dict:
    return _destination(_T.MCP_TOOL, tool.name, None, endpoint_host(tool.transport))


@dataclass(frozen=True)
class _SecretHolder:
    """A kind of row a slot's secret can be bound to, and how to describe one."""

    model: type[Model]
    secret_field: str
    related: tuple[str, ...]
    describe: Callable[[Model], dict]


_HOLDERS: dict[PluginResourceType, _SecretHolder] = {
    _T.LLM_CONFIG: _SecretHolder(
        LLMConfig,
        SECRET_BINDING_FIELDS[EntityType.LLM_CONFIG],
        ("model__llm_provider",),
        _installed_llm_config,
    ),
    _T.EMBEDDING_CONFIG: _SecretHolder(
        EmbeddingConfig,
        SECRET_BINDING_FIELDS[EntityType.EMBEDDING_CONFIG],
        ("model__embedding_provider",),
        _installed_embedding_config,
    ),
    _T.MCP_TOOL: _SecretHolder(
        McpTool, SECRET_BINDING_FIELDS[EntityType.MCP_TOOL], (), _installed_mcp_tool
    ),
}


def installed_destinations(
    plugins: list[Plugin],
    resources_by_plugin: dict[int, list[PluginResource]],
    existing: Collection[tuple[str, int]],
) -> dict[tuple[int, str], list[dict]]:
    """(plugin id, slot name) -> where a value entered for that slot now would be sent.

    Mirrors `PluginSecretSlotService.replace`: a slot whose secret exists sends to
    every LLM config, embedding config and MCP tool of the org bound to that secret,
    the org's own rows and edits included. A slot whose secret was deleted would be
    bound as the plugin file binds it, so it sends to those plugin rows that still
    exist. One query per kind of row, for the whole batch.

    Args:
        resources_by_plugin: Every registry row of each plugin, keyed by plugin id.
        existing: `(resource type, object id)` of the registry rows that still exist.
    """
    secret_by_slot: dict[tuple[int, str], int | None] = {}
    fallback_by_slot: dict[tuple[int, str], list[tuple[PluginResourceType, int]]] = {}
    for plugin in plugins:
        links = resources_by_plugin.get(plugin.pk, [])
        for slot in plugin.secret_slots:
            key = (plugin.pk, slot["name"])
            secret_by_slot[key] = next(
                (
                    link.object_id
                    for link in links
                    if link.resource_type == _T.SECRET
                    and link.manifest_ref == slot["name"]
                    and (_T.SECRET.value, link.object_id) in existing
                ),
                None,
            )
            if secret_by_slot[key] is None:
                fallback_by_slot[key] = _bound_plugin_rows(plugin, slot["name"], links)

    secret_ids = {secret_id for secret_id in secret_by_slot.values() if secret_id is not None}
    fallback_ids: dict[PluginResourceType, set[int]] = defaultdict(set)
    for rows in fallback_by_slot.values():
        for resource_type, object_id in rows:
            fallback_ids[resource_type].add(object_id)

    org_by_plugin = {plugin.pk: plugin.org_id for plugin in plugins}
    rows_by_secret: dict[int, list[tuple[PluginResourceType, Model]]] = defaultdict(list)
    rows_by_key: dict[tuple[PluginResourceType, int], Model] = {}
    for resource_type, holder in _HOLDERS.items():
        if not secret_ids and not fallback_ids[resource_type]:
            continue
        secret_column = f"{holder.secret_field}_id"
        rows = holder.model.objects.filter(
            Q(**{f"{secret_column}__in": secret_ids}) | Q(pk__in=fallback_ids[resource_type]),
            org_id__in=set(org_by_plugin.values()),
        ).select_related(*holder.related)
        for row in rows:
            rows_by_key[(resource_type, row.pk)] = row
            secret_id = getattr(row, secret_column)
            if secret_id in secret_ids:
                rows_by_secret[secret_id].append((resource_type, row))

    result = {}
    for key, secret_id in secret_by_slot.items():
        org_id = org_by_plugin[key[0]]
        if secret_id is not None:
            rows = rows_by_secret[secret_id]
        else:
            rows = [
                (resource_type, rows_by_key[(resource_type, object_id)])
                for resource_type, object_id in fallback_by_slot[key]
                if (resource_type, object_id) in rows_by_key
            ]
        result[key] = [
            _HOLDERS[resource_type].describe(row)
            for resource_type, row in sorted(
                rows, key=lambda item: (_DESTINATION_ORDER[item[0]], item[1].pk)
            )
            if row.org_id == org_id
        ]
    return result


def _bound_plugin_rows(
    plugin: Plugin, slot: str, links: list[PluginResource]
) -> list[tuple[PluginResourceType, int]]:
    """The plugin rows its file binds `slot` to, by registry link."""
    rows = []
    for binding in plugin.manifest.get("secret_bindings", []):
        if binding["slot"] != slot:
            continue
        resource_type = IMPORTED_ENTITIES[EntityType(binding["entity"])].resource_type
        rows += [
            (resource_type, link.object_id)
            for link in links
            if link.resource_type == resource_type and link.manifest_ref == str(binding["ref"])
        ]
    return rows
