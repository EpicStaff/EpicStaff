import posixpath
from collections import Counter

from tables.import_export.enums import EntityType
from tables.import_export.services.inspect_service import InspectService

from plugins.manifest import PluginPackage
from plugins.resource_types import IMPORTED_ENTITIES, PluginResourceType
from plugins.services.secret_destinations import bundle_destinations

# Must not suggest the page is torn down before data can leave: a sandboxed page
# can navigate away carrying what it was given, and the host only notices afterwards.
UI_WARNING = (
    "This plugin runs its own code in a sandboxed page. The page can use what is listed "
    "below with the permissions of whoever opens it, and anything it can see could be "
    "sent to the plugin's author."
)
CODE_WARNING = (
    "This plugin contains Python code that will run in your organization's sandbox. "
    "Review it before installing."
)
KNOWLEDGE_WARNING = (
    "Knowledge is indexed in the background after install. The plugin shows "
    "'Preparing knowledge' until indexing finishes."
)


def build_preview(
    package: PluginPackage, *, missing_permissions: list[dict], conflicts: list[dict]
) -> dict:
    """The install dialog's review step: what the plugin contains and would be allowed to do."""
    manifest = package.manifest
    contents = _contents(package)
    code_review_items = InspectService().inspect(package.resources)["review_items"]

    warnings = []
    if package.ui_entry:
        warnings.append(UI_WARNING)
    if code_review_items:
        warnings.append(CODE_WARNING)
    if package.has_knowledge:
        warnings.append(KNOWLEDGE_WARNING)

    flow_names = {flow["id"]: flow.get("name", "") for flow in package.entities(EntityType.GRAPH)}
    destinations = bundle_destinations(package)
    return {
        "plugin": {
            "plugin_id": manifest.id,
            "version": manifest.version,
            "name": manifest.name,
            "description": manifest.description,
            "icon_data_url": package.icon_data_url,
            "format_version": manifest.format_version,
            "bridge_version": manifest.bridge,
            "has_ui": bool(package.ui_entry),
        },
        "contents": contents,
        "content_counts": dict(Counter(item["type"] for item in contents)),
        "access": [
            {
                "alias": entry.alias,
                "type": entry.type,
                "ref": entry.ref,
                "resource_name": flow_names.get(entry.ref, ""),
                "actions": list(entry.actions),
            }
            for entry in manifest.access
        ],
        "secret_slots": [
            {
                "name": slot.name,
                "description": slot.description,
                "secret_name": package.secret_name(slot.name),
                "destinations": destinations.get(slot.name, []),
            }
            for slot in manifest.secret_slots
        ],
        "code_review_items": code_review_items,
        "has_knowledge": package.has_knowledge,
        "ui_asset_count": len(package.ui_assets),
        "warnings": warnings,
        "missing_permissions": missing_permissions,
        "conflicts": conflicts,
        "can_install": not missing_permissions and not conflicts,
    }


def _contents(package: PluginPackage) -> list[dict]:
    items = []
    for entity_type, imported in IMPORTED_ENTITIES.items():
        for entity in package.entities(entity_type):
            items.append(
                {
                    "type": imported.resource_type.value,
                    "ref": str(entity["id"]),
                    "name": entity.get(imported.name_key) or "",
                }
            )
    for slot in package.manifest.secret_slots:
        items.append(
            {
                "type": PluginResourceType.SECRET.value,
                "ref": slot.name,
                "name": package.secret_name(slot.name),
            }
        )
    for entry in package.manifest.knowledge:
        items.append(
            {
                "type": PluginResourceType.SOURCE_COLLECTION.value,
                "ref": entry.name,
                "name": entry.name,
                "documents": [posixpath.basename(path) for path in entry.documents],
            }
        )
    for entry in package.manifest.storage_files:
        items.append(
            {
                "type": PluginResourceType.STORAGE_FILE.value,
                "ref": entry.path,
                "name": package.storage_path(entry.path),
            }
        )
    return items
