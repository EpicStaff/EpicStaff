"""What a plugin action needs on the rows it writes or removes, shared by install and uninstall."""

from collections.abc import Iterable

from rbac.access.effective import EffectivePermissions
from rbac.models.enums import Permission, ResourceType

from plugins.resource_types import RBAC_RESOURCE_TYPES, PluginResourceType


def missing_permissions_on(
    resource_types: Iterable[PluginResourceType],
    action: Permission,
    effective: EffectivePermissions,
) -> list[dict]:
    """`action` on `plugins` and on the RBAC type of every given row type, where the caller lacks it.

    Install passes CREATE and the types a bundle contains; uninstall passes DELETE
    and the types it would remove. Both answer in the same shape, so the install and
    delete refusals (and their previews) read alike.

    Returns:
        `[{"resource_type": <rbac code>, "action": <action code>}]` sorted by resource
        type; empty when nothing is missing.
    """
    required = {ResourceType.PLUGINS} | {
        RBAC_RESOURCE_TYPES[resource_type] for resource_type in resource_types
    }
    return [
        {"resource_type": resource_type.value, "action": action.name.lower()}
        for resource_type in sorted(required, key=lambda item: item.value)
        if not effective.can(resource_type, action)
    ]
