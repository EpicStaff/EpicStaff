"""Built-in roles as declarative state, reconciled into the database.

`builtin_roles.json` is the complete definition of the four built-in roles: name,
description and every permission they hold. `BuiltInRoleSeeder.seed()` makes the
database match it exactly -- a permission absent from the file is revoked, by design.
`manage.py seed_builtin_roles` runs it on every container start, so changing a
built-in role never needs a data migration.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.db.models import Count

from rbac.access.bitmask import actions_to_bitmask, bitmask_to_actions
from rbac.access.catalog import applicable_actions_for
from rbac.models import Role, RolePermission
from rbac.models.enums import BuiltInRole, ResourceType

BUILTIN_ROLES_PATH = Path(__file__).with_name("builtin_roles.json")

_BUILTIN_ROLE_NAMES = frozenset(
    {BuiltInRole.SUPERADMIN, BuiltInRole.ORG_ADMIN, BuiltInRole.MEMBER, BuiltInRole.VIEWER}
)
_ROLE_KEYS = frozenset({"description", "permissions"})


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    """`object_pairs_hook` for `json.loads`: reject a JSON object with a repeated key.

    Plain `json.loads` silently keeps the last value of a repeated key -- a second
    "Member" block, or a repeated "flows" key inside one role's permissions, would pass
    validation and silently revoke or widen a grant. Applied at every nesting level, so a
    duplicate top-level role name and a duplicate resource key within one role's
    `permissions` are both caught.
    """
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate key {key!r}")
        seen[key] = value
    return seen


class _RoleState(NamedTuple):
    description: str
    masks: dict[str, int]


@dataclass
class SeedResult:
    """What one `seed()` run did, as human-readable lines."""

    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class BuiltInRoleSeeder:
    """Reconcile the built-in roles in the database with `builtin_roles.json`."""

    def __init__(self, path: Path | None = None):
        self.path = path or BUILTIN_ROLES_PATH

    def seed(self) -> SeedResult:
        """Make the built-in roles match the file exactly.

        The whole file is validated before anything is written, and the writes run in
        one transaction. Creates a missing role, corrects its description, and creates,
        updates or deletes `RolePermission` rows so each role holds exactly the listed
        actions. A built-in role in the database that the file does not name is
        reported, never deleted: memberships cascade from it.

        Raises:
            ImproperlyConfigured: The file is missing, malformed, or grants something the
                catalog does not allow. Nothing is written.
        """
        desired = self._load()
        result = SeedResult()
        with transaction.atomic():
            for name, state in desired.items():
                _reconcile_role(name, state, result)
            unlisted = Role.objects.filter(is_built_in=True, org__isnull=True).exclude(
                name__in=list(desired)
            )
            for role in unlisted:
                result.warnings.append(
                    f"{role.name}: built-in role not in {self.path.name}; left untouched"
                )
            # org is NULL for every built-in role, so nothing enforces one row per name;
            # _reconcile_role only ever touches the lowest id.
            duplicates = (
                Role.objects.filter(is_built_in=True, org__isnull=True)
                .values("name")
                .annotate(count=Count("id"))
                .filter(count__gt=1)
            )
            for row in duplicates:
                result.warnings.append(
                    f"{row['name']}: {row['count']} built-in rows share this name; "
                    "only the lowest id is reconciled"
                )
        return result

    def _load(self) -> dict[str, _RoleState]:
        try:
            raw = json.loads(
                self.path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_keys
            )
        except (OSError, ValueError) as error:
            raise ImproperlyConfigured(f"Cannot read {self.path}: {error}") from error
        if not isinstance(raw, dict):
            raise ImproperlyConfigured(
                f"{self.path}: expected an object mapping role name to definition"
            )

        errors: list[str] = []
        missing = sorted(_BUILTIN_ROLE_NAMES - raw.keys())
        unknown = sorted(raw.keys() - _BUILTIN_ROLE_NAMES)
        if missing:
            # Absence means revocation, so a dropped role would silently lose everything.
            errors.append(f"missing built-in roles: {missing}")
        if unknown:
            errors.append(f"unknown roles: {unknown}")
        roles = {
            name: _parse_role(name, definition, errors)
            for name, definition in raw.items()
            if name in _BUILTIN_ROLE_NAMES
        }
        if errors:
            raise ImproperlyConfigured(f"{self.path} is invalid:\n  - " + "\n  - ".join(errors))
        return roles


def _parse_role(name: str, definition, errors: list[str]) -> _RoleState | None:
    if not isinstance(definition, dict) or definition.keys() != _ROLE_KEYS:
        errors.append(f"{name}: must have exactly the keys {sorted(_ROLE_KEYS)}")
        return None
    description, permissions = definition["description"], definition["permissions"]
    if not isinstance(description, str) or not description.strip():
        errors.append(f"{name}.description: must be a non-empty string")
    if not isinstance(permissions, dict):
        errors.append(f"{name}.permissions: must map resource type to a list of actions")
        return None
    if name == BuiltInRole.SUPERADMIN and permissions:
        errors.append(f"{name}: must grant nothing; its authority is User.is_superadmin")
    masks = {}
    for resource_type, actions in permissions.items():
        mask = _parse_grant(f"{name}.{resource_type}", resource_type, actions, errors)
        if mask is not None:
            masks[resource_type] = mask
    return _RoleState(description, masks)


def _parse_grant(where: str, resource_type: str, actions, errors: list[str]) -> int | None:
    if resource_type not in ResourceType.values:
        errors.append(f"{where}: unknown resource type")
        return None
    if not isinstance(actions, list) or not actions:
        errors.append(f"{where}: must be a non-empty list of actions; remove the key instead")
        return None
    # Platform actions are never in applicable_actions, so this rejects them too.
    applicable = applicable_actions_for(resource_type)
    not_grantable = [action for action in actions if action not in applicable]
    if not_grantable:
        errors.append(f"{where}: {not_grantable} not grantable; applicable: {applicable}")
        return None
    if len(set(actions)) != len(actions):
        errors.append(f"{where}: duplicate actions")
        return None
    return actions_to_bitmask(actions)


def _reconcile_role(name: str, state: _RoleState, result: SeedResult) -> None:
    # Built-in names have no DB uniqueness (org is NULL), so pick deterministically.
    role = Role.objects.filter(name=name, is_built_in=True, org__isnull=True).order_by("id").first()
    if role is None:
        role = Role.objects.create(
            name=name, description=state.description, is_built_in=True, org=None
        )
        result.changes.append(f"{name}: created")
    elif role.description != state.description:
        role.description = state.description
        role.save(update_fields=["description", "updated_at"])
        result.changes.append(f"{name}: description updated")

    current = {row.resource_type: row for row in role.permissions_set.all()}
    for resource_type, mask in state.masks.items():
        row = current.pop(resource_type, None)
        if row is None:
            RolePermission.objects.create(role=role, resource_type=resource_type, permissions=mask)
            result.changes.append(
                f"{name}.{resource_type}: granted {_describe(resource_type, mask)}"
            )
        elif row.permissions != mask:
            result.changes.append(
                f"{name}.{resource_type}: {_describe(resource_type, row.permissions)}"
                f" -> {_describe(resource_type, mask)}"
            )
            row.permissions = mask
            row.save(update_fields=["permissions"])
    # Whatever the file no longer lists is revoked.
    for resource_type, row in current.items():
        result.changes.append(
            f"{name}.{resource_type}: removed {_describe(resource_type, row.permissions)}"
        )
        row.delete()


def _describe(resource_type: str, mask: int) -> str:
    actions = bitmask_to_actions(mask, applicable_actions_for(resource_type))
    return f"{', '.join(actions) or 'none'} ({mask})"
