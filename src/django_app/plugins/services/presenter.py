from collections import Counter, defaultdict

from django.conf import settings

from plugins.models import Plugin, PluginResource
from plugins.resource_types import ACCESS_RESOURCE_TYPES, RESOURCE_MODELS, PluginResourceType
from plugins.services.secret_destinations import installed_destinations


class PluginPresenter:
    """Build the API shape of installed plugins.

    Names of linked rows are looked up in one query per resource type for the whole
    batch, and so are the destinations of the secret slots. A row the org has since
    deleted is reported with `exists: false` and a null name instead of disappearing.
    """

    def present(self, plugin: Plugin) -> dict:
        """One plugin, with the full list of what it installed."""
        resources_by_plugin, names, destinations = self._resolve([plugin])
        return self._plugin(
            plugin, resources_by_plugin[plugin.pk], names, destinations, include_resources=True
        )

    def present_many(self, plugins: list[Plugin]) -> list[dict]:
        resources_by_plugin, names, destinations = self._resolve(plugins)
        return [
            self._plugin(
                plugin, resources_by_plugin[plugin.pk], names, destinations, include_resources=False
            )
            for plugin in plugins
        ]

    def _resolve(self, plugins: list[Plugin]):
        resources_by_plugin: dict[int, list[PluginResource]] = defaultdict(list)
        ids_by_type: dict[str, set[int]] = defaultdict(set)
        for resource in PluginResource.objects.filter(plugin__in=plugins).order_by("id"):
            resources_by_plugin[resource.plugin_id].append(resource)
            ids_by_type[resource.resource_type].add(resource.object_id)

        names: dict[tuple[str, int], str] = {}
        for resource_type, ids in ids_by_type.items():
            resource_model = RESOURCE_MODELS[PluginResourceType(resource_type)]
            rows = resource_model.model.objects.filter(pk__in=ids).values_list(
                "pk", resource_model.display_field
            )
            names.update({(resource_type, pk): name for pk, name in rows})
        destinations = installed_destinations(plugins, resources_by_plugin, names.keys())
        return resources_by_plugin, names, destinations

    def _plugin(
        self,
        plugin: Plugin,
        resources: list[PluginResource],
        names: dict[tuple[str, int], str],
        destinations: dict[tuple[int, str], list[dict]],
        *,
        include_resources: bool,
    ) -> dict:
        by_ref = {
            (resource.resource_type, resource.manifest_ref): resource for resource in resources
        }

        def linked(resource_type: PluginResourceType, ref) -> tuple[int | None, str | None]:
            resource = by_ref.get((resource_type.value, str(ref)))
            if resource is None:
                return None, None
            name = names.get((resource.resource_type, resource.object_id))
            return (resource.object_id, name) if name is not None else (None, None)

        access = []
        for entry in plugin.access:
            resource_id, resource_name = linked(ACCESS_RESOURCE_TYPES[entry["type"]], entry["ref"])
            access.append(
                {
                    "alias": entry["alias"],
                    "type": entry["type"],
                    "actions": entry["actions"],
                    "resource_id": resource_id,
                    "resource_name": resource_name,
                }
            )

        secret_slots = []
        for slot in plugin.secret_slots:
            secret_id, secret_name = linked(PluginResourceType.SECRET, slot["name"])
            secret_slots.append(
                {
                    "name": slot["name"],
                    "description": slot["description"],
                    "secret_id": secret_id,
                    "secret_name": secret_name,
                    "configured": secret_id is not None,
                    "destinations": destinations[(plugin.pk, slot["name"])],
                }
            )

        data = {
            "id": plugin.pk,
            "plugin_id": plugin.plugin_id,
            "version": plugin.version,
            "name": plugin.name,
            "description": plugin.description,
            "icon_data_url": plugin.icon_data_url,
            "format_version": plugin.format_version,
            "bridge_version": plugin.bridge_version,
            "has_ui": bool(plugin.ui_entry),
            "status": "suspended" if plugin.suspended else plugin.state,
            "state": plugin.state,
            "status_reason": plugin.status_reason,
            "suspended": plugin.suspended,
            "suspended_at": plugin.suspended_at,
            "access": access,
            "secret_slots": secret_slots,
            "contents": dict(Counter(resource.resource_type for resource in resources)),
            "dev_mode_available": settings.PLUGINS_DEV_MODE,
            "dev_ui_url": plugin.dev_ui_url or None,
            "dev_ui_user": plugin.dev_ui_user_id,
            "created_by": plugin.created_by_id,
            "created_at": plugin.created_at,
            "updated_at": plugin.updated_at,
        }
        if include_resources:
            data["resources"] = [
                {
                    "type": resource.resource_type,
                    "resource_id": resource.object_id,
                    "name": names.get((resource.resource_type, resource.object_id)),
                    "manifest_ref": resource.manifest_ref,
                    "exists": (resource.resource_type, resource.object_id) in names,
                }
                for resource in resources
            ]
        return data
