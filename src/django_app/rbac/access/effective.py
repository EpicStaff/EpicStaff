from collections.abc import Mapping
from dataclasses import dataclass, field

from rbac.access.audit_history import UNLIMITED, grants_audit, history_days_of, is_within
from rbac.access.bitmask import bitmask_to_actions
from rbac.access.catalog import (
    RESOURCE_TYPE_METADATA,
    grantable_bits_for,
)
from rbac.models.enums import Permission


@dataclass(frozen=True)
class RoleGrant:
    """Everything a role hands to its holders: per-resource bits and the audit
    history limit. The escalation ceiling compares this as one value, so a
    caller cannot check the bits and forget the limit."""

    by_resource: Mapping[str, int]
    audit_history_days: int = UNLIMITED

    @classmethod
    def of_role(cls, role) -> "RoleGrant":
        """What `role` grants. The caller loads the role with
        `prefetch_related("permissions_set")` and `select_related("audit_policy")`."""
        return cls(
            by_resource=EffectivePermissions.bits_of(role),
            audit_history_days=history_days_of(role),
        )


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

    `audit_history_days` is how many days back the principal may read
    audit data in this org; 0 = unlimited (always 0 for superadmin).

    Future:
    The resolver returns an object, not a tuple. This is the
    forward-compatible integration point for per-entity overrides —
    `apply_entity_overrides()` will land on this same class.
    """

    is_superadmin: bool
    role: object | None  # Role instance or None for superadmin
    by_resource: dict[str, int] = field(default_factory=dict)
    audit_history_days: int = UNLIMITED

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
        return {row.resource_type: row.permissions for row in role.permissions_set.all()}

    @classmethod
    def from_role(cls, role) -> "EffectivePermissions":
        """Build a non-superadmin EffectivePermissions from a Role's
        permission rows and audit policy. `role.permissions_set` should be
        prefetched and `audit_policy` select_related by the caller."""
        return cls(
            is_superadmin=False,
            role=role,
            by_resource=cls.bits_of(role),
            audit_history_days=history_days_of(role),
        )

    def covers(self, grant: RoleGrant) -> bool:
        """Whether everything `grant` hands out is within these permissions.

        The escalation ceiling as a pure comparison, shared by role
        authoring (the bits being written into a role) and role assignment
        (the bits the assigned role grants) so the two cannot drift. A
        resource absent from this principal's map counts as zero, so requesting
        nothing on a resource is never an escalation. Superadmin covers
        everything.

        Only the bits grantable **on that resource** are compared
        (`grantable_bits_for`). Grantability is per-resource -- `use` is an
        action of `secrets` and `chats` only -- and a row written before
        the catalog settled (an older custom role, say) can still hold a bit
        that is not an action of its own resource. Comparing those lets dead
        data refuse a legitimate grant: historically, Org Admin (`flows: 31`)
        could not assign Viewer (`flows: 66`), whose USE bit was enforced
        nowhere for flows.

        When the grant reads or exports audit data, its audit history limit
        must also be no wider than this principal's own (`is_within`):
        unlimited is the widest, so a limited principal can grant neither
        unlimited nor more days than they have. A grant without an audit
        action is decided by the bits alone.
        """
        if self.is_superadmin:
            return True
        bits_covered = all(
            not (
                (mask & grantable_bits_for(resource_type)) & ~self.by_resource.get(resource_type, 0)
            )
            for resource_type, mask in grant.by_resource.items()
        )
        if not bits_covered:
            return False
        return not grants_audit(grant.by_resource) or is_within(
            self.audit_history_days, grant.audit_history_days
        )

    def to_action_codes(self) -> str | dict[str, list[str]]:
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
