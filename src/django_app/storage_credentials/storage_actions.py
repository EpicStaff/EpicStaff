from rbac.access.effective import EffectivePermissions
from rbac.models.enums import Permission, ResourceType
from src.shared.models.storage_scope import StorageAction


def storage_actions_for(effective_permissions: EffectivePermissions) -> frozenset[StorageAction]:
    """Return what a run's code may do to the files attached to it, given who runs it.

    READ needs FILES:READ. WRITE needs READ plus both FILES:CREATE and FILES:UPDATE,
    because storage cannot tell creating an object from overwriting one. DELETE needs
    READ plus FILES:DELETE. Without READ nothing is allowed. Superadmin holds all three.
    """
    if not effective_permissions.can(ResourceType.FILES, Permission.READ):
        return frozenset()
    actions = {StorageAction.READ}
    if effective_permissions.can(ResourceType.FILES, Permission.CREATE) and (
        effective_permissions.can(ResourceType.FILES, Permission.UPDATE)
    ):
        actions.add(StorageAction.WRITE)
    if effective_permissions.can(ResourceType.FILES, Permission.DELETE):
        actions.add(StorageAction.DELETE)
    return frozenset(actions)
