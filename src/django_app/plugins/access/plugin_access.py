"""Who may use a plugin in an organization: the one rule behind the left bar, login and the gateway.

A person may use a plugin in an organization when all of these hold:

- they are an active user and a member of the organization, and the organization is active;
- the plugin's grant to the organization is active and the plugin is running (`usable()`);
- their membership role's actions on the plugin include `read`.

Rights come from the membership only. `is_superadmin` is never consulted: a SuperAdmin who is
not a member of an organization may use no plugin there, and one who is gets their role's
actions, like anyone else (the built-in Superadmin role of the bootstrap SuperAdmin's
membership gets Org Admin's, while they are a SuperAdmin; see
`plugin_permissions.holds_plugin_role`). A role's actions come from
`plugin_permissions.role_actions_by_grant`, the resolution the Roles matrix uses too.
"""

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db.models.functions import Lower
from epicstaff_plugin.contracts.manifest import READ_ACTION
from rbac.models import Organization, OrganizationUser

from plugins.access.plugin_permissions import (
    holds_plugin_role,
    role_actions_by_grant,
    role_plugin_actions,
    stored_permissions_by_role,
)
from plugins.exceptions import PluginNotFoundError
from plugins.models import Plugin, PluginGrant, PluginState
from plugins.models.grant import PluginGrantQuerySet


@dataclass(frozen=True)
class PersonPluginAccess:
    """A person's use of a plugin in one organization, through the plugin's grant there."""

    user: object
    organization: Organization
    grant: PluginGrant
    actions: list[str]


@dataclass(frozen=True)
class GatewayPersonFacts:
    """What the gateway check needs to know about the person a login token names.

    `user` is None when the user no longer exists, `grant` when the token's grant is no longer
    a usable grant of this plugin to this organization, and `membership` when the person is no
    member of it. `may_use` is the rule above for this grant.
    """

    user: object | None
    grant: PluginGrant | None
    membership: OrganizationUser | None
    actions: list[str]
    may_use: bool


def loginable_plugin(identifier: str) -> Plugin:
    """Return the running plugin `identifier` if people can log in to it: it has a backend.

    A login token is only for the plugin's own `/api/`, so a plugin without a backend has none.

    Raises:
        PluginNotFoundError: No such plugin, it is not running, or it has no backend.
    """
    plugin = (
        Plugin.objects.select_related("current_package")
        .defer("current_package__icon_bytes")
        .filter(identifier=identifier, state=PluginState.RUNNING, current_package__isnull=False)
        .first()
    )
    if plugin is None or plugin.current_package.parsed_manifest.backend is None:
        raise PluginNotFoundError()
    return plugin


def accesses_in_organization(
    user, org_id: int, grants: PluginGrantQuerySet
) -> list[PersonPluginAccess]:
    """Return `user`'s access to each plugin of `grants` they may use in organization `org_id`.

    `grants` are usable grants of that organization (`.usable()`), read only when the person
    is an active member of it; the result keeps their order. At most three queries: the
    membership, the grants, and the stored actions of a custom role.
    """
    membership = _membership(user, org_id)
    if membership is None:
        return []
    grants = list(grants)
    readable = _readable(user, membership, grants)
    return [
        PersonPluginAccess(
            user=user, organization=membership.org, grant=grant, actions=readable[grant.pk]
        )
        for grant in grants
        if grant.pk in readable
    ]


def resolve_person_plugin_access(user, org_id: int, plugin: Plugin) -> PersonPluginAccess | None:
    """Return how `user` may use `plugin` in organization `org_id`, or None if they may not."""
    accesses = accesses_in_organization(
        user, org_id, PluginGrant.objects.filter(org_id=org_id, plugin=plugin).usable()
    )
    return accesses[0] if accesses else None


def eligible_people(
    user_ids: list[int], org_id: int, plugin: Plugin
) -> list[tuple[OrganizationUser, PersonPluginAccess]]:
    """Return each of `user_ids` who may use `plugin` in organization `org_id`, by user id.

    The rule above, for many people at once: each comes with their membership (user, role
    with its permission rows, and organization) and their access. At most four queries,
    whatever the number of people: the grant, the memberships, their roles' permission rows,
    and the stored actions of their custom roles.
    """
    grant = PluginGrant.objects.filter(org_id=org_id, plugin=plugin).usable().first()
    if grant is None or not user_ids:
        return []
    memberships = list(
        OrganizationUser.objects.select_related("user", "role", "org")
        .prefetch_related("role__permissions_set")
        .filter(org_id=org_id, org__is_active=True, user_id__in=user_ids, user__is_active=True)
        .order_by("user_id")
    )
    stored = stored_permissions_by_role([membership.role for membership in memberships], grant.pk)
    manifest = grant.plugin.current_package.parsed_manifest
    eligible = []
    for membership in memberships:
        if not holds_plugin_role(membership.user, membership.role):
            continue
        actions = role_plugin_actions(membership.role, manifest, stored.get(membership.role_id, 0))
        if READ_ACTION in actions:
            eligible.append(
                (
                    membership,
                    PersonPluginAccess(
                        user=membership.user,
                        organization=membership.org,
                        grant=grant,
                        actions=actions,
                    ),
                )
            )
    return eligible


def eligible_accesses(user, plugin: Plugin) -> list[PersonPluginAccess]:
    """Return `user`'s access to `plugin` in every organization they may use it in, by name.

    Two queries, plus one per custom-role membership whose organization has the plugin.
    """
    if not _is_active_person(user):
        return []
    memberships = list(
        OrganizationUser.objects.select_related("role", "org")
        .filter(user=user, org__is_active=True)
        .order_by(Lower("org__name"), "org_id")
    )
    grants = {
        grant.org_id: grant
        for grant in PluginGrant.objects.filter(
            plugin=plugin, org_id__in=[membership.org_id for membership in memberships]
        ).usable()
    }
    accesses = []
    for membership in memberships:
        grant = grants.get(membership.org_id)
        if grant is None:
            continue
        actions = _readable(user, membership, [grant]).get(grant.pk)
        if actions is not None:
            accesses.append(
                PersonPluginAccess(
                    user=user, organization=membership.org, grant=grant, actions=actions
                )
            )
    return accesses


def eligible_organizations(user, plugin: Plugin) -> list[Organization]:
    """Return the organizations `user` may use `plugin` in, sorted by name."""
    return [access.organization for access in eligible_accesses(user, plugin)]


def gateway_person_facts(
    *, user_id: int, org_id: int, grant_id: int, identifier: str
) -> GatewayPersonFacts:
    """Gather what the gateway needs about the person, organization and grant a token names.

    Each fact is read separately, so the gateway can tell a token that is no longer acceptable
    (the user or the grant is gone) from a person who may no longer use the plugin. At most
    four queries.
    """
    user = get_user_model().objects.filter(pk=user_id).first()
    grant = (
        PluginGrant.objects.filter(pk=grant_id, org_id=org_id, plugin__identifier=identifier)
        .usable()
        .first()
    )
    membership = _membership(user, org_id) if user is not None else None
    actions = (
        role_actions_by_grant(membership.role, [grant])[grant.pk]
        if membership is not None and grant is not None and holds_plugin_role(user, membership.role)
        else []
    )
    return GatewayPersonFacts(
        user=user,
        grant=grant,
        membership=membership,
        actions=actions,
        may_use=membership is not None and READ_ACTION in actions,
    )


def _is_active_person(user) -> bool:
    # A caller that is not a user (the system API key) is no person and holds no membership.
    return isinstance(user, get_user_model()) and user.is_active


def _membership(user, org_id: int) -> OrganizationUser | None:
    """The person's membership of organization `org_id`, if both are active, with role and org."""
    if not _is_active_person(user):
        return None
    return (
        OrganizationUser.objects.select_related("role", "org")
        .filter(user=user, org_id=org_id, org__is_active=True)
        .first()
    )


def _readable(
    user, membership: OrganizationUser, grants: list[PluginGrant]
) -> dict[int, list[str]]:
    if not holds_plugin_role(user, membership.role):
        return {}
    actions_by_grant = role_actions_by_grant(membership.role, grants)
    return {
        grant_id: actions
        for grant_id, actions in actions_by_grant.items()
        if READ_ACTION in actions
    }
