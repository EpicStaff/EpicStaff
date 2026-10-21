"""The plugin rows of the Roles matrix: reading and writing what custom roles may do in plugins.

Visibility and the verb gate are rbac's own (`RoleManagementService`), so a role or an
organization the caller cannot see answers exactly as the roles API does: 404
`role_not_found` / `organization_not_found`. The ceiling is the caller's own actions on each
plugin in that organization, resolved by `plugin_permissions` like every other plugin check.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.db.models.functions import Lower
from epicstaff_plugin.contracts.manifest import READ_ACTION
from epicstaff_plugin.problems import Problem
from rbac.access.bitmask import actions_to_bitmask
from rbac.access.cross_org_resolver import OrgScope
from rbac.access.effective import EffectivePermissions
from rbac.access.resolver import PermissionResolver
from rbac.exceptions import (
    OrganizationNotFoundError,
    OrgMembershipRequiredError,
    PermissionEscalationError,
    RoleNotFoundError,
)
from rbac.governance.roles import RoleManagementService
from rbac.models import Organization, Role
from rbac.models.enums import Permission, ResourceType

from plugins.access.plugin_permissions import (
    declared_actions,
    role_actions_by_grant,
    role_plugin_actions,
)
from plugins.audit import log_role_plugin_actions
from plugins.exceptions import InvalidPluginRolePermissionsError
from plugins.models import GrantState, Plugin, PluginGrant, PluginRolePermission, PluginState

_ROLES = ResourceType.ROLES.value


@dataclass(frozen=True)
class PluginRoleRow:
    """One plugin row of the matrix.

    `ceiling` is what the caller may grant on it (empty when the role is not editable);
    `granted` is what the role has (empty for a role that does not exist yet).
    """

    plugin: Plugin
    ceiling: list[str]
    granted: list[str]


@dataclass(frozen=True)
class OrganizationPluginRows:
    organization: Organization
    rows: list[PluginRoleRow]


@dataclass(frozen=True)
class RolePluginPermissions:
    role: Role
    organization: Organization | None
    editable: bool
    rows: list[PluginRoleRow]


@dataclass(frozen=True)
class RequestedPluginActions:
    """One `{plugin_identifier, actions}` entry of a write, as received."""

    plugin_identifier: str
    actions: list[str]


class PluginRolePermissionService:
    """Reads and replaces custom roles' actions on the plugins granted to their organization."""

    _roles = RoleManagementService()
    _resolver = PermissionResolver()

    def rows_for_organization(self, actor, org_id: int) -> OrganizationPluginRows:
        """Return the plugin rows a new custom role of `org_id` would show, with the ceiling.

        Raises:
            OrganizationNotFoundError: No such organization, or the caller cannot read roles
                in it.
        """
        organization, effective = self._readable_organization(actor, org_id)
        grants = _usable_grants(org_id)
        ceilings = _ceilings(effective, grants, editable=_can_edit_roles(effective))
        return OrganizationPluginRows(
            organization=organization,
            rows=[
                PluginRoleRow(plugin=grant.plugin, ceiling=ceilings[grant.pk], granted=[])
                for grant in grants
            ],
        )

    def role_permissions(
        self, actor, role_id, org_id: int | None, scopes: list[OrgScope] | None = None
    ) -> RolePluginPermissions:
        """Return a role's plugin rows and the actions it has on each.

        A custom role shows the plugins of its own organization (`org_id` is ignored). A
        built-in role shows its manifest defaults, read-only: for `org_id`'s plugins when
        given, otherwise for every plugin usable in an organization where the caller may
        read roles (every running plugin for a SuperAdmin), each once. `scopes` is the
        caller's cross-org scopes already resolved by the door gate, if any.

        Raises:
            RoleNotFoundError: No such role, or a custom role the caller cannot read.
            OrganizationNotFoundError: A built-in role read for an organization that does
                not exist or where the caller cannot read roles.
        """
        role = self._roles.get_role_for_read(actor=actor, role_id=role_id, scopes=scopes)
        if role.is_built_in:
            return self._built_in_role_permissions(actor, role, org_id, scopes)
        return self._custom_role_permissions(actor, role)

    def replace_role_permissions(
        self, actor, role_id, requested: list[RequestedPluginActions]
    ) -> RolePluginPermissions:
        """Replace a custom role's actions on every plugin usable in its organization.

        A usable plugin left out of `requested` loses its actions; rows of grants that are
        not usable now (a suspended grant, a stopped plugin) are left as they are. The role
        row is locked for the write, like rbac's own role update.

        The ceiling applies to what changes: every action added or removed on a plugin must
        be one the caller holds there. An action the caller does not hold may stay as it is
        (a SuperAdmin gave it), so an Org Admin can still save the rest of the role.

        Raises:
            RoleNotFoundError: No such role, or one the caller can neither read nor update.
            BuiltInRoleImmutableError: The role is built-in.
            PermissionDenied: The caller may read roles in the organization but not update
                them.
            InvalidPluginRolePermissionsError: An entry names a plugin that is not usable in
                the role's organization or names it twice, or lists actions the plugin does
                not declare, repeats one, or gives any without `read`.
            PermissionEscalationError: An action added or removed is outside the caller's
                own actions on that plugin in the organization.
        """
        with transaction.atomic():
            role = _locked_role(role_id)
            self._roles.assert_mutable(role)
            effective = self._roles.resolve_for_write(actor, role.org_id, action=Permission.UPDATE)
            self._roles.assert_can(effective=effective, action=Permission.UPDATE)
            grants = _usable_grants(role.org_id)
            wanted = _validated_actions(requested, grants)
            before = role_actions_by_grant(role, grants)
            ceilings = _ceilings(effective, grants, editable=True)
            for grant in grants:
                changed = set(wanted.get(grant.pk, [])) ^ set(before[grant.pk])
                if not changed <= set(ceilings[grant.pk]):
                    raise PermissionEscalationError()
            changes = _write_rows(role, grants, wanted, actor)
        for grant, before, after in changes:
            log_role_plugin_actions(
                actor,
                role_id=role.pk,
                org_id=role.org_id,
                identifier=grant.plugin.identifier,
                before=before,
                after=after,
            )
        return self._custom_role_permissions(actor, role)

    def _readable_organization(
        self, actor, org_id: int
    ) -> tuple[Organization, EffectivePermissions]:
        organization = Organization.objects.filter(pk=org_id).first()
        if organization is None:
            raise OrganizationNotFoundError()
        try:
            effective = self._resolver.resolve(user=actor, org_id=org_id)
        except OrgMembershipRequiredError:
            raise OrganizationNotFoundError() from None
        if not effective.can(_ROLES, Permission.READ):
            raise OrganizationNotFoundError()
        return organization, effective

    def _custom_role_permissions(self, actor, role: Role) -> RolePluginPermissions:
        # The caller already passed the read or write check for this role, so this only
        # works out what they may change; like rbac's write responses, it does not re-check
        # read, so a write-without-read grant still gets its response.
        effective = self._resolver.resolve(user=actor, org_id=role.org_id)
        editable = _can_edit_roles(effective)
        grants = _usable_grants(role.org_id)
        granted = role_actions_by_grant(role, grants)
        ceilings = _ceilings(effective, grants, editable=editable)
        return RolePluginPermissions(
            role=role,
            organization=role.org,
            editable=editable,
            rows=[
                PluginRoleRow(
                    plugin=grant.plugin,
                    ceiling=ceilings[grant.pk],
                    granted=granted[grant.pk],
                )
                for grant in grants
            ],
        )

    def _built_in_role_permissions(
        self, actor, role: Role, org_id: int | None, scopes: list[OrgScope] | None
    ) -> RolePluginPermissions:
        if org_id is not None:
            organization, _ = self._readable_organization(actor, org_id)
            plugins = [grant.plugin for grant in _usable_grants(org_id)]
        else:
            organization = None
            readable_org_ids = self._roles.resolve_readable_org_ids(actor, scopes=scopes)
            plugins = _plugins_usable_in(readable_org_ids)
        return RolePluginPermissions(
            role=role,
            organization=organization,
            editable=False,
            rows=[
                PluginRoleRow(
                    plugin=plugin,
                    ceiling=[],
                    granted=role_plugin_actions(role, plugin.current_package.parsed_manifest),
                )
                for plugin in plugins
            ],
        )


def _can_edit_roles(effective: EffectivePermissions) -> bool:
    return effective.can(_ROLES, Permission.UPDATE)


def _usable_grants(org_id: int) -> list[PluginGrant]:
    return list(PluginGrant.objects.filter(org_id=org_id).usable())


def _plugins_usable_in(org_ids: set[int] | None) -> list[Plugin]:
    """Running plugins with an active grant in one of `org_ids` (`None`: every running plugin)."""
    plugins = (
        Plugin.objects.filter(state=PluginState.RUNNING, current_package__isnull=False)
        .select_related("current_package")
        .defer("current_package__icon_bytes")
        .order_by(Lower("name"), "identifier")
    )
    if org_ids is not None:
        active_grants = PluginGrant.objects.filter(
            plugin=OuterRef("pk"), org_id__in=org_ids, state=GrantState.ACTIVE
        )
        plugins = plugins.filter(Exists(active_grants))
    return list(plugins)


def _ceilings(
    effective: EffectivePermissions, grants: Iterable[PluginGrant], *, editable: bool
) -> dict[int, list[str]]:
    """The caller's own actions on each grant's plugin, by grant id; empty when not editable.

    A SuperAdmin's ceiling is every action the plugin declares; anyone else's is what their
    membership role has on the plugin in this organization.
    """
    grants = list(grants)
    if not editable:
        return {grant.pk: [] for grant in grants}
    if effective.is_superadmin:
        return {
            grant.pk: declared_actions(grant.plugin.current_package.parsed_manifest)
            for grant in grants
        }
    return role_actions_by_grant(effective.role, grants)


def _locked_role(role_id) -> Role:
    try:
        return Role.objects.select_for_update().get(pk=int(role_id))
    except (TypeError, ValueError, Role.DoesNotExist):
        raise RoleNotFoundError() from None


def _validated_actions(
    requested: list[RequestedPluginActions], grants: list[PluginGrant]
) -> dict[int, list[str]]:
    """Check every entry against the usable grants; return the actions by grant id."""
    by_identifier = {grant.plugin.identifier: grant for grant in grants}
    problems: list[Problem] = []
    wanted: dict[int, list[str]] = {}
    seen: set[str] = set()
    for index, entry in enumerate(requested):
        loc = f"plugins[{index}]"
        grant = by_identifier.get(entry.plugin_identifier)
        if grant is None:
            problems.append(
                Problem(
                    f"{loc}.plugin_identifier",
                    f"'{entry.plugin_identifier}' is not a running plugin granted to the "
                    "role's organization",
                )
            )
            continue
        if entry.plugin_identifier in seen:
            problems.append(
                Problem(
                    f"{loc}.plugin_identifier",
                    f"'{entry.plugin_identifier}' is listed more than once",
                )
            )
            continue
        seen.add(entry.plugin_identifier)
        manifest = grant.plugin.current_package.parsed_manifest
        action_problems = _action_problems(entry.actions, declared_actions(manifest))
        problems.extend(Problem(f"{loc}.actions", message) for message in action_problems)
        if not action_problems:
            wanted[grant.pk] = entry.actions
    if problems:
        raise InvalidPluginRolePermissionsError(problems)
    return wanted


def _action_problems(actions: list[str], declared: list[str]) -> list[str]:
    problems = [
        f"'{action}' is not an action this plugin declares"
        for action in dict.fromkeys(actions)
        if action not in declared
    ]
    problems.extend(
        f"lists '{action}' more than once"
        for action in dict.fromkeys(actions)
        if actions.count(action) > 1
    )
    if actions and READ_ACTION not in actions:
        problems.append("must include read (View) to give any other action")
    return problems


def _write_rows(
    role: Role, grants: list[PluginGrant], wanted: dict[int, list[str]], actor
) -> list[tuple[PluginGrant, list[str], list[str]]]:
    """Store `wanted` for every usable grant; return `(grant, before, after)` per change."""
    existing = {
        row.grant_id: row
        for row in PluginRolePermission.objects.select_for_update().filter(
            role=role, grant__in=grants
        )
    }
    changes = []
    for grant in grants:
        manifest = grant.plugin.current_package.parsed_manifest
        row = existing.get(grant.pk)
        before_bits = row.permissions if row else 0
        after_bits = actions_to_bitmask(wanted.get(grant.pk, []))
        if after_bits == before_bits:
            continue
        if after_bits == 0:
            row.delete()
        elif row is None:
            PluginRolePermission.objects.create(
                grant=grant, role=role, permissions=after_bits, updated_by=actor
            )
        else:
            row.permissions = after_bits
            row.updated_by = actor
            row.save(update_fields=["permissions", "updated_by", "updated_at"])
        changes.append(
            (
                grant,
                role_plugin_actions(role, manifest, before_bits),
                role_plugin_actions(role, manifest, after_bits),
            )
        )
    return changes
