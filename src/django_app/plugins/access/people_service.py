"""The people a plugin's service account may know about and act for.

Only people who may use the plugin in the service account's organization exist for it, by
the one rule of `plugin_access`: an active member of the active organization whose role has
`read` on the plugin, under an active grant of a running plugin. Everyone else is "not
found", members without `read` included, so a plugin never learns about people who cannot
use it.
"""

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from rbac.access.effective import EffectivePermissions
from rbac.models import OrganizationUser, Role
from rbac.models.enums import BuiltInRole

from plugins.access.plugin_access import eligible_people, resolve_person_plugin_access
from plugins.access.plugin_permissions import is_built_in_superadmin_role
from plugins.audit import log_on_behalf_of_refused
from plugins.exceptions import OnBehalfOfNotAllowedError, PersonNotFoundError
from plugins.models import PluginGrant

# EpicStaff's ids are signed 64-bit integers.
MAX_USER_ID = 2**63 - 1


@dataclass(frozen=True)
class PluginPersonFacts:
    """A person who may use the plugin, with their plugin actions and their own EpicStaff rights.

    `epicstaff_permissions` come from the membership role, in the shape of
    `/api/permissions/me/`'s `permissions`; never `"*"`, even for a SuperAdmin. EpicStaff
    does not check them on the plugin's calls: the plugin reads them to decide what it does
    for the person.
    """

    user: object
    organization_id: int
    organization_name: str
    plugin_permissions: list[str]
    epicstaff_permissions: dict[str, list[str]]


class PluginPeopleService:
    def on_behalf_of(self, grant: PluginGrant, user_id: int):
        """Return the user a service account call names, when the plugin may act for them.

        Only the plugin's rule is checked (may the person use the plugin here), never the
        person's own EpicStaff rights: the plugin's declared access still caps every call.

        Raises:
            OnBehalfOfNotAllowedError: The user is unknown, inactive, no member of the
                grant's active organization, holds no `read` on the plugin, or the grant is
                not active; one answer for every case.
        """
        user = (
            get_user_model().objects.filter(pk=user_id).first()
            if 0 < user_id <= MAX_USER_ID
            else None
        )
        access = (
            resolve_person_plugin_access(user, grant.org_id, grant.plugin)
            if user is not None
            else None
        )
        if access is None:
            log_on_behalf_of_refused(
                identifier=grant.plugin.identifier, org_id=grant.org_id, user_id=user_id
            )
            raise OnBehalfOfNotAllowedError()
        return user

    def person(self, grant: PluginGrant, user_id: int) -> PluginPersonFacts:
        """Return one person who may use the plugin in the grant's organization.

        Raises:
            PersonNotFoundError: Anyone else, including members without `read`.
        """
        people = self.people(grant, [user_id])
        if not people:
            raise PersonNotFoundError()
        return people[0]

    def people(self, grant: PluginGrant, user_ids: list[int]) -> list[PluginPersonFacts]:
        """Return those of `user_ids` who may use the plugin there, sorted by user id.

        At most six queries, whatever the number of ids: four for the people, two for the
        Org Admin role when one of them holds the built-in Superadmin role.
        """
        valid_ids = [user_id for user_id in user_ids if 0 < user_id <= MAX_USER_ID]
        eligible = eligible_people(valid_ids, grant.org_id, grant.plugin)
        org_admin_role = (
            _built_in_org_admin_role()
            if any(is_built_in_superadmin_role(membership.role) for membership, _ in eligible)
            else None
        )
        return [
            _facts(membership, access.actions, org_admin_role) for membership, access in eligible
        ]


def _facts(
    membership: OrganizationUser, actions: list[str], org_admin_role: Role | None
) -> PluginPersonFacts:
    # The built-in Superadmin role holds no permissions: its holder's authority is the
    # account's superadmin flag, which a plugin is never told about. Org Admin's are the
    # most a plugin may assume such a person can do in the organization. Only a current
    # SuperAdmin with that role is eligible at all (`holds_plugin_role`).
    role = org_admin_role if is_built_in_superadmin_role(membership.role) else membership.role
    return PluginPersonFacts(
        user=membership.user,
        organization_id=membership.org_id,
        organization_name=membership.org.name,
        plugin_permissions=actions,
        epicstaff_permissions=EffectivePermissions.from_role(role).to_action_codes(),
    )


def _built_in_org_admin_role() -> Role:
    return Role.objects.prefetch_related("permissions_set").get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
