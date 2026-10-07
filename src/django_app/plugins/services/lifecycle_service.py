"""Suspend, resume and delete installed plugins."""

from collections import Counter, defaultdict
from contextlib import suppress
from dataclasses import dataclass
from functools import partial

from django.apps import apps
from django.db import router, transaction
from django.db.models import Model
from django.db.models.deletion import Collector
from django.utils import timezone
from rbac.access.effective import EffectivePermissions
from rbac.access.resolver import PermissionResolver
from rbac.governance.delete_collector import build_affected_resources, summarize
from rbac.models.enums import Permission
from redis import RedisError
from tables.exceptions import KeyValueTableNotFoundError
from tables.models import EmbeddingConfig, LLMConfig, Session, StorageFile
from tables.services.key_value_table_service import KeyValueTableService
from tables.services.knowledge_services.collection_management_service import (
    CollectionManagementService,
)
from tables.services.session_manager_service import SessionManagerService
from tables.services.storage_service import get_storage_backend
from tables.services.storage_service.db_sync import StorageFileSync
from tables.services.storage_service.path_utils import storage_key
from utils.logger import logger

from plugins.exceptions import PluginDeleteForbiddenError
from plugins.models import Plugin, PluginResource
from plugins.resource_types import RESOURCE_MODELS, PluginResourceType
from plugins.services.permission_checks import missing_permissions_on

_T = PluginResourceType

LIVE_SESSION_STATUSES = (
    Session.SessionStatus.PENDING,
    Session.SessionStatus.RUN,
    Session.SessionStatus.WAIT_FOR_USER,
)

# The order delete walks the registry: what references a row goes before it, so
# no step deletes something a later step still needs to find by its own path.
DELETE_ORDER: tuple[PluginResourceType, ...] = (
    _T.FLOW,
    _T.KEY_VALUE_TABLE,
    _T.AGENT_DEFINITION,
    _T.SURFACE,
    _T.PYTHON_CODE_TOOL,
    _T.MCP_TOOL,
    _T.WEBHOOK_TRIGGER,
    _T.SOURCE_COLLECTION,
    _T.LLM_CONFIG,
    _T.EMBEDDING_CONFIG,
    _T.LLM_MODEL,
    _T.EMBEDDING_MODEL,
    _T.SECRET,
    _T.STORAGE_FILE,
)

# A custom model cascades to every config using it, so it is deleted only when
# no config outside the plugin uses it; otherwise the org has adopted it.
_MODEL_USERS: dict[PluginResourceType, tuple[type[Model], str]] = {
    _T.LLM_MODEL: (LLMConfig, "model_id"),
    _T.EMBEDDING_MODEL: (EmbeddingConfig, "model_id"),
}


@dataclass(frozen=True)
class _ExternalUsage:
    """One way an org row outside the plugin can reference a plugin row."""

    target_type: PluginResourceType
    model_label: str
    target_field: str
    owner_type: PluginResourceType
    owner_field: str


# Org rows that lose a plugin row when the plugin is deleted. To report another
# kind of reference, add an entry; test_plugin_lifecycle checks every field exists.
EXTERNAL_USAGES: tuple[_ExternalUsage, ...] = (
    _ExternalUsage(_T.FLOW, "tables.SubGraphNode", "subgraph", _T.FLOW, "graph"),
    _ExternalUsage(_T.KEY_VALUE_TABLE, "tables.KeyValueNode", "key_value_table", _T.FLOW, "graph"),
    _ExternalUsage(_T.AGENT_DEFINITION, "tables.TaskNode", "agent_definition", _T.FLOW, "graph"),
    _ExternalUsage(_T.AGENT_DEFINITION, "tables.AgentNode", "agent_definition", _T.FLOW, "graph"),
    _ExternalUsage(
        _T.SURFACE, "agents.AgentDefaultSurface", "surface", _T.AGENT_DEFINITION, "agent_definition"
    ),
    _ExternalUsage(
        _T.LLM_CONFIG, "agents.AgentDefinition", "llm_config", _T.AGENT_DEFINITION, "id"
    ),
    _ExternalUsage(
        _T.LLM_CONFIG, "agents.AgentDefinition", "fcm_llm_config", _T.AGENT_DEFINITION, "id"
    ),
    _ExternalUsage(
        _T.PYTHON_CODE_TOOL, "agents.SurfacePythonTool", "python_tool", _T.SURFACE, "surface"
    ),
    _ExternalUsage(_T.MCP_TOOL, "agents.SurfaceMcpTool", "mcp_tool", _T.SURFACE, "surface"),
    _ExternalUsage(
        _T.SOURCE_COLLECTION, "agents.SurfaceKnowledge", "collection", _T.SURFACE, "surface"
    ),
    _ExternalUsage(
        _T.STORAGE_FILE, "agents.SurfaceStorageItem", "storage_file", _T.SURFACE, "surface"
    ),
    _ExternalUsage(_T.STORAGE_FILE, "tables.GraphStorageFile", "storage_file", _T.FLOW, "graph"),
    _ExternalUsage(_T.SECRET, "tables.LLMConfig", "api_key_secret", _T.LLM_CONFIG, "id"),
    _ExternalUsage(
        _T.SECRET, "tables.EmbeddingConfig", "api_key_secret", _T.EMBEDDING_CONFIG, "id"
    ),
    _ExternalUsage(_T.SECRET, "tables.McpTool", "auth_secret", _T.MCP_TOOL, "id"),
)


class PluginLifecycleService:
    """Turn an installed plugin off and on, and remove everything it installed."""

    def suspend(self, plugin: Plugin) -> Plugin:
        """Turn the plugin fully off; idempotent.

        The guard refuses its flows, agents and tools from the moment this commits.
        Live sessions of its flows are stopped after the commit, so a rolled-back
        suspend never stops anything.
        """
        with transaction.atomic():
            plugin = Plugin.objects.select_for_update().get(pk=plugin.pk)
            if not plugin.suspended:
                plugin.suspended = True
                plugin.suspended_at = timezone.now()
                plugin.save(update_fields=["suspended", "suspended_at", "updated_at"])
            transaction.on_commit(partial(_stop_live_sessions, plugin.pk))
        return plugin

    def resume(self, plugin: Plugin) -> Plugin:
        """Reverse suspend; idempotent."""
        with transaction.atomic():
            plugin = Plugin.objects.select_for_update().get(pk=plugin.pk)
            if plugin.suspended:
                plugin.suspended = False
                plugin.suspended_at = None
                plugin.save(update_fields=["suspended", "suspended_at", "updated_at"])
        return plugin

    def delete_preview(self, plugin: Plugin, *, user) -> dict:
        """Describe what deleting the plugin would remove, and what `user` lacks to do it. Writes nothing."""
        registry = _Registry.load(plugin)
        deletable = registry.deletable_rows()
        effective = PermissionResolver().resolve(user=user, org_id=plugin.org_id)
        flow_ids = registry.existing_ids(_T.FLOW)
        sessions = Session.objects.filter(graph_id__in=flow_ids)
        storage_file_count = len(registry.existing_ids(_T.STORAGE_FILE))

        return {
            "plugin": {
                "id": plugin.pk,
                "plugin_id": plugin.plugin_id,
                "name": plugin.name,
                "version": plugin.version,
            },
            "resources": registry.describe(),
            "resource_counts": dict(Counter(resource_type.value for resource_type, _ in deletable)),
            "session_count": sessions.count(),
            "live_session_count": sessions.filter(status__in=LIVE_SESSION_STATUSES).count(),
            "affected_resources": build_affected_resources(
                summarize(_collect(deletable)), {"storage_files": storage_file_count}
            ),
            "external_usages": registry.external_usages(),
            "missing_permissions": _missing_delete_permissions(deletable, effective),
        }

    def delete(self, plugin: Plugin, *, user) -> None:
        """Remove every row the plugin installed, edits and run history included, then the plugin.

        `user` needs delete on every resource type that will be removed, checked
        before anything is written. The plugin is then suspended and committed, so
        no trigger can start a new session while its rows are removed. Its flows'
        live sessions are stopped by the Session pre_delete signal once the cascade
        commits, in soft-delete mode too, so they are not stopped here a second
        time. Rows the org already deleted are skipped. Storage objects are removed
        after the delete commits, best effort: an object left behind is
        unreachable, a row left behind would not be.

        Raises:
            PluginDeleteForbiddenError: `user` lacks delete on a type that would
                be removed. Nothing is deleted. In the rare case the plugin gained
                a row of a new type between the first check and the delete, the
                refusal comes after the suspend, so the plugin stays suspended.
        """
        effective = PermissionResolver().resolve(user=user, org_id=plugin.org_id)
        _require_delete_permissions(_Registry.load(plugin).deletable_rows(), effective)

        Plugin.objects.filter(pk=plugin.pk, suspended=False).update(
            suspended=True, suspended_at=timezone.now()
        )

        with transaction.atomic():
            plugin = Plugin.objects.select_for_update().get(pk=plugin.pk)
            registry = _Registry.load(plugin)
            deletable = registry.deletable_rows()
            # Re-entering a deleted slot secret adds a registry row after the first
            # check, so check again against exactly the rows this loop removes.
            _require_delete_permissions(deletable, effective)
            storage_keys = []
            for resource_type, instance in deletable:
                if resource_type == _T.SOURCE_COLLECTION:
                    CollectionManagementService.delete_collection(instance.pk)
                elif resource_type == _T.STORAGE_FILE:
                    storage_keys.append(storage_key(plugin.org_id, instance.path))
                    StorageFileSync.on_delete(plugin.org_id, instance.path)
                elif resource_type == _T.KEY_VALUE_TABLE:
                    # Takes the table's row lock first, like a table delete from its own
                    # page, so a flow writing entries right now cannot deadlock with it.
                    # Its rows go with it; the org's own nodes using it are unlinked.
                    # Not found means it was deleted meanwhile, e.g. from its own page.
                    with suppress(KeyValueTableNotFoundError):
                        KeyValueTableService().delete_table(instance)
                elif _still_exists(instance):
                    # An earlier step may have cascaded to it, e.g. an agent's owned surface.
                    instance.delete()
            _delete_empty_plugin_folders(plugin)
            plugin.delete()
            transaction.on_commit(partial(_discard_storage_objects, storage_keys))


class _Registry:
    """The registry rows of one plugin, resolved to the org rows that still exist."""

    def __init__(self, plugin: Plugin, links: list[PluginResource], rows: dict):
        self.plugin = plugin
        self.links = links
        # (resource type, object id) -> the live org row
        self.rows = rows

    @classmethod
    def load(cls, plugin: Plugin) -> "_Registry":
        links = list(PluginResource.objects.filter(plugin=plugin).order_by("id"))
        ids_by_type: dict[PluginResourceType, set[int]] = defaultdict(set)
        for link in links:
            ids_by_type[PluginResourceType(link.resource_type)].add(link.object_id)
        rows = {}
        for resource_type, ids in ids_by_type.items():
            resource_model = RESOURCE_MODELS[resource_type]
            for instance in resource_model.model.objects.filter(
                pk__in=ids, **{resource_model.org_field: plugin.org_id}
            ):
                rows[(resource_type, instance.pk)] = instance
        return cls(plugin, links, rows)

    def existing_ids(self, resource_type: PluginResourceType) -> set[int]:
        return {pk for kind, pk in self.rows if kind == resource_type}

    def deletable_rows(self) -> list[tuple[PluginResourceType, Model]]:
        """Live rows in delete order, minus custom models the org's own configs use."""
        kept_models = self._models_used_outside()
        return [
            (resource_type, self.rows[(resource_type, pk)])
            for resource_type in DELETE_ORDER
            for pk in sorted(self.existing_ids(resource_type))
            if (resource_type, pk) not in kept_models
        ]

    def describe(self) -> list[dict]:
        kept_models = self._models_used_outside()
        described = []
        for link in self.links:
            key = (PluginResourceType(link.resource_type), link.object_id)
            if key in kept_models:
                continue
            instance = self.rows.get(key)
            display_field = RESOURCE_MODELS[key[0]].display_field
            described.append(
                {
                    "type": link.resource_type,
                    "resource_id": link.object_id,
                    "name": getattr(instance, display_field) if instance is not None else None,
                    "exists": instance is not None,
                }
            )
        return described

    def external_usages(self) -> list[dict]:
        """Org rows outside the plugin that reference a plugin row and will lose it."""
        users_by_target: dict[tuple[PluginResourceType, int], set] = defaultdict(set)
        for usage in EXTERNAL_USAGES:
            target_ids = self.existing_ids(usage.target_type)
            if not target_ids:
                continue
            model = apps.get_model(usage.model_label)
            references = (
                model.objects.filter(**{f"{usage.target_field}__in": target_ids})
                .exclude(**{f"{usage.owner_field}__in": self.existing_ids(usage.owner_type)})
                .values_list(f"{usage.target_field}_id", _id_column(usage.owner_field))
            )
            for target_id, owner_id in references:
                if owner_id is not None:
                    users_by_target[(usage.target_type, target_id)].add(
                        (usage.owner_type, owner_id)
                    )
        if not users_by_target:
            return []

        owner_names = _names({owner for owners in users_by_target.values() for owner in owners})
        target_names = _names(set(users_by_target))
        return [
            {
                "type": target_type.value,
                "resource_id": target_id,
                "name": target_names.get((target_type, target_id)),
                "used_by": [
                    {
                        "type": owner_type.value,
                        "resource_id": owner_id,
                        "name": owner_names.get((owner_type, owner_id)),
                    }
                    for owner_type, owner_id in sorted(users_by_target[(target_type, target_id)])
                ],
            }
            for target_type, target_id in sorted(users_by_target)
        ]

    def _models_used_outside(self) -> set[tuple[PluginResourceType, int]]:
        kept = set()
        for resource_type, (config_model, model_column) in _MODEL_USERS.items():
            model_ids = self.existing_ids(resource_type)
            if not model_ids:
                continue
            config_type = _T.LLM_CONFIG if resource_type == _T.LLM_MODEL else _T.EMBEDDING_CONFIG
            used = (
                config_model.objects.filter(**{f"{model_column}__in": model_ids})
                .exclude(pk__in=self.existing_ids(config_type))
                .values_list(model_column, flat=True)
            )
            kept.update((resource_type, model_id) for model_id in used)
        return kept


def _missing_delete_permissions(
    rows: list[tuple[PluginResourceType, Model]], effective: EffectivePermissions
) -> list[dict]:
    return missing_permissions_on(
        {resource_type for resource_type, _ in rows}, Permission.DELETE, effective
    )


def _require_delete_permissions(
    rows: list[tuple[PluginResourceType, Model]], effective: EffectivePermissions
) -> None:
    if missing := _missing_delete_permissions(rows, effective):
        raise PluginDeleteForbiddenError(missing)


def _id_column(field: str) -> str:
    return "id" if field == "id" else f"{field}_id"


def _names(keys: set[tuple[PluginResourceType, int]]) -> dict[tuple[PluginResourceType, int], str]:
    ids_by_type: dict[PluginResourceType, set[int]] = defaultdict(set)
    for resource_type, pk in keys:
        ids_by_type[resource_type].add(pk)
    names = {}
    for resource_type, ids in ids_by_type.items():
        resource_model = RESOURCE_MODELS[resource_type]
        for pk, name in resource_model.model.objects.filter(pk__in=ids).values_list(
            "pk", resource_model.display_field
        ):
            names[(resource_type, pk)] = name
    return names


def _collect(rows: list[tuple[PluginResourceType, Model]]) -> Collector:
    """A Collector over every given row at once, so shared cascades are counted once."""
    instances_by_model: dict[type[Model], list[Model]] = defaultdict(list)
    for _, instance in rows:
        instances_by_model[type(instance)].append(instance)
    collector = Collector(using=router.db_for_write(Plugin))
    for instances in instances_by_model.values():
        collector.collect(instances)
    return collector


def _still_exists(instance: Model) -> bool:
    return type(instance)._default_manager.filter(pk=instance.pk).exists()


def _delete_empty_plugin_folders(plugin: Plugin) -> None:
    """Remove the folder rows install created for the plugin's files, unless the org added files there."""
    for folder in (f"plugins/{plugin.plugin_id}/", "plugins/"):
        has_children = (
            StorageFile.objects.filter(org_id=plugin.org_id, path__startswith=folder)
            .exclude(path=folder)
            .exists()
        )
        if has_children:
            return
        StorageFile.objects.filter(org_id=plugin.org_id, path=folder, item_type="folder").delete()


def _stop_live_sessions(plugin_pk: int) -> None:
    """Ask crew and manager to stop every live session of the plugin's flows. Best effort."""
    flow_ids = PluginResource.objects.filter(
        plugin_id=plugin_pk, resource_type=_T.FLOW
    ).values_list("object_id", flat=True)
    session_ids = Session.objects.filter(
        graph_id__in=list(flow_ids), status__in=LIVE_SESSION_STATUSES
    ).values_list("pk", flat=True)
    session_manager = SessionManagerService()
    for session_id in session_ids:
        # The plugin is already off and the guard refuses new runs; a session we
        # cannot reach still ends at its time-to-live, so log and go on.
        try:
            session_manager.stop_session(session_id)
        except RedisError:
            logger.exception("Could not stop session {} of plugin {}", session_id, plugin_pk)


def _discard_storage_objects(keys: list[str]) -> None:
    if keys:
        get_storage_backend(organization_prefix="").discard_keys(keys)
