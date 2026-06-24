from dataclasses import dataclass, field
from typing import Optional, Union

from tables.models.rbac_models.rbac_enums import Permission
from tables.services.rbac.permission_catalog import RESOURCE_TYPE_METADATA
from tables.services.rbac.utils.permission_bitmask import bitmask_to_actions


@dataclass
class EffectivePermissions:
    """EffectivePermissions: the resolved permission state for a single
    (user, org) pair.
    Resolved (user, org) -> permissions.

    `is_superadmin=True` bypasses all permission checks (.can returns
    True unconditionally; .to_action_codes returns "*").

    `by_resource` maps resource_type (string code) to a Permission
    bitmask integer. Missing keys mean zero permissions on that
    resource type.

    Future:
    The resolver returns an object, not a tuple. This is the
    forward-compatible integration point for per-entity overrides —
    `apply_entity_overrides()` will land on this same class.
    """

    is_superadmin: bool
    role: Optional[object]  # Role instance or None for superadmin
    by_resource: dict[str, int] = field(default_factory=dict)

    def can(self, resource_type: str, action: Permission) -> bool:
        if self.is_superadmin:
            return True
        mask = self.by_resource.get(resource_type, 0)
        return bool(mask & int(action))

    def to_action_codes(self) -> Union[str, dict[str, list[str]]]:
        """Serialize for the wire — either "*" (superadmin) or
        {resource_type: [action_code, ...]}.

        Iterates the catalog (not `by_resource`) so every catalog
        resource_type is always a key in the response — missing or
        zero-bitmask resources surface as []. Stable response shape
        simplifies FE iteration."""
        if self.is_superadmin:
            return "*"
        return {
            entry["code"]: bitmask_to_actions(
                self.by_resource.get(entry["code"], 0),
                applicable=entry["applicable_actions"],
            )
            for entry in RESOURCE_TYPE_METADATA
        }
