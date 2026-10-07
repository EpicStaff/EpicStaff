"""Checks an install must pass before it writes anything, shared by preview and install."""

from rbac.access.effective import EffectivePermissions
from rbac.models.enums import Permission, ResourceType
from tables.import_export.enums import EntityType, NodeType
from tables.models import KeyValueTable, Secret, StorageFile
from tables.services.key_value_table_service import MODE_PERMISSIONS

from plugins.exceptions import InvalidPluginSecretsError, PluginAlreadyInstalledError
from plugins.manifest import PluginPackage
from plugins.models import Plugin
from plugins.resource_types import IMPORTED_ENTITIES, PluginResourceType
from plugins.services.permission_checks import missing_permissions_on

MAX_SECRET_VALUE_LENGTH = 4096


def reject_if_installed(package: PluginPackage, org_id: int) -> None:
    """Raise 409 when the org already has a plugin with this id.

    Raises:
        PluginAlreadyInstalledError: the prototype does not update in place yet.
    """
    installed_version = (
        Plugin.objects.filter(org_id=org_id, plugin_id=package.manifest.id)
        .values_list("version", flat=True)
        .first()
    )
    if installed_version is not None:
        raise PluginAlreadyInstalledError(package.manifest.id, installed_version)


def missing_permissions(package: PluginPackage, effective: EffectivePermissions) -> list[dict]:
    """Create permissions the installer lacks for what the plugin would create.

    Installing must not let `plugins:create` create anything the installer could not
    create directly, so every bundled type needs its own create permission.
    """
    contained = [
        imported.resource_type
        for entity_type, imported in IMPORTED_ENTITIES.items()
        if package.entities(entity_type)
    ]
    if package.manifest.secret_slots:
        contained.append(PluginResourceType.SECRET)
    if package.manifest.knowledge:
        contained.append(PluginResourceType.SOURCE_COLLECTION)
    if package.manifest.storage_files:
        contained.append(PluginResourceType.STORAGE_FILE)
    missing = missing_permissions_on(contained, Permission.CREATE, effective)
    missing += [
        item
        for item in _missing_key_value_node_permissions(package, effective)
        if item not in missing
    ]
    return sorted(
        missing, key=lambda item: (item["resource_type"], int(Permission[item["action"].upper()]))
    )


def _missing_key_value_node_permissions(
    package: PluginPackage, effective: EffectivePermissions
) -> list[dict]:
    """The key_value_tables permissions a bundled Key-Value node needs to bind its table.

    The importer binds a node's table only for an installer holding every permission
    of the node's mode, and leaves it unbound otherwise. A plugin flow with an unbound
    node fails on every run, so the install is refused up front instead.
    """
    needed: set[Permission] = set()
    for flow in package.entities(EntityType.GRAPH):
        for node in flow.get("nodes") or []:
            if (
                node.get("node_type") == NodeType.KEY_VALUE_NODE
                and node.get("key_value_table") is not None
            ):
                # An unknown mode fails the import's own validation later.
                needed.update(MODE_PERMISSIONS.get(node.get("mode", "read"), ()))
    return [
        {"resource_type": ResourceType.KEY_VALUE_TABLES.value, "action": permission.name.lower()}
        for permission in sorted(needed)
        if not effective.can(ResourceType.KEY_VALUE_TABLES, permission)
    ]


def find_conflicts(package: PluginPackage, org_id: int) -> list[dict]:
    """Org rows already holding a name the install would create.

    Secrets are unique per org by name, key-value tables by name regardless of
    case, and storage files by path; overwriting or reusing any of them would hand
    the org's own data to the plugin.
    """
    secret_names = [package.secret_name(slot.name) for slot in package.manifest.secret_slots]
    taken_secrets = set(
        Secret.objects.filter(org_id=org_id, name__in=secret_names).values_list("name", flat=True)
    )
    storage_paths = [package.storage_path(entry.path) for entry in package.manifest.storage_files]
    taken_paths = set(
        StorageFile.objects.filter(org_id=org_id, path__in=storage_paths).values_list(
            "path", flat=True
        )
    )
    # Already `<slug>__<name>`. One query per table: a plugin ships a handful, and
    # iexact here is exactly the rule the table's unique constraint enforces.
    table_names = [table["name"] for table in package.entities(EntityType.KEY_VALUE_TABLE)]
    taken_tables = [
        name
        for name in table_names
        if KeyValueTable.objects.filter(org_id=org_id, name__iexact=name).exists()
    ]
    return (
        [
            {"type": "secret", "name": name, "message": f"A secret named '{name}' already exists."}
            for name in secret_names
            if name in taken_secrets
        ]
        + [
            {
                "type": "key_value_table",
                "name": name,
                "message": f"A key-value table named '{name}' already exists.",
            }
            for name in taken_tables
        ]
        + [
            {
                "type": "storage_file",
                "name": path,
                "message": f"A file already exists at '{path}'.",
            }
            for path in storage_paths
            if path in taken_paths
        ]
    )


def check_secret_values(declared: list[str], secrets: dict, *, require_every_slot: bool) -> None:
    """Require a non-blank value for declared slots only.

    Install needs a value for every declared slot; re-entering secrets later
    needs at least one value and may leave the other slots alone.

    Raises:
        InvalidPluginSecretsError: a slot is missing, unknown, blank or too long.
    """
    errors = []
    if require_every_slot:
        errors += [
            {"slot": name, "message": "A value is required."}
            for name in declared
            if name not in secrets
        ]
    elif not secrets:
        errors.append({"slot": "", "message": "Enter a value for at least one secret slot."})
    errors += [
        {"slot": name, "message": "The plugin has no such secret slot."}
        for name in sorted(secrets)
        if name not in declared
    ]
    for name in declared:
        if name not in secrets:
            continue
        value = secrets[name]
        if not isinstance(value, str) or not value.strip():
            errors.append({"slot": name, "message": "The value must not be blank."})
        elif len(value) > MAX_SECRET_VALUE_LENGTH:
            errors.append(
                {
                    "slot": name,
                    "message": f"The value is longer than {MAX_SECRET_VALUE_LENGTH} characters.",
                }
            )
    if errors:
        raise InvalidPluginSecretsError(errors)
