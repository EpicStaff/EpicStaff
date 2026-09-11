from dataclasses import dataclass, field
from typing import Mapping, Optional, Union

from tables.models.rbac_models.rbac_enums import Permission
from tables.services.rbac.permission_catalog import (
    GRANTABLE_ACTION_BITS,
    RESOURCE_TYPE_METADATA,
)
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

    @staticmethod
    def bits_of(role) -> dict[str, int]:
        """A Role's per-resource bitmasks. The single way to read a role's
        bits, so the resolver and the escalation ceiling cannot disagree
        about what a role grants. `role.permissions_set` should be
        prefetched by the caller."""
        return {
            row.resource_type: row.permissions for row in role.permissions_set.all()
        }

    @classmethod
    def from_role(cls, role) -> "EffectivePermissions":
        """Build a non-superadmin EffectivePermissions from a Role's
        permission rows. `role.permissions_set` should be prefetched by
        the caller when resolving many roles at once."""
        return cls(is_superadmin=False, role=role, by_resource=cls.bits_of(role))

    def covers(self, by_resource: Mapping[str, int]) -> bool:
        """Whether every bit in `by_resource` is within these permissions.

        The escalation ceiling as a pure comparison, shared by role
        authoring (the bits being written into a role) and role assignment
        (the bits the assigned role grants) so the two cannot drift. A
        resource absent from this principal's map counts as zero, so requesting
        nothing on a resource is never an escalation. Superadmin covers
        everything.

        Only `GRANTABLE_ACTION_BITS` are compared. USE and LIST are not in the
        catalog, are rejected by role validation and are read by no code, but
        they do occur in the built-in seeds -- comparing them would let dead
        data refuse a legitimate grant (Org Admin, `flows: 31`, could not
        assign Viewer, `flows: 66`).
        """
        if self.is_superadmin:
            return True
        return all(
            not (
                (mask & GRANTABLE_ACTION_BITS) & ~self.by_resource.get(resource_type, 0)
            )
            for resource_type, mask in by_resource.items()
        )

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
