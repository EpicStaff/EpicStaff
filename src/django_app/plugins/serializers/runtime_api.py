"""Documents of the `/api/plugin-runtime/` endpoints a plugin's backend calls.

Responses are built with the SDK's service-account API models, the plugin side's own
definition of them, so EpicStaff cannot answer with a shape the SDK does not read. Only the
lookup body is a DRF serializer, for EpicStaff's usual 400 `invalid`.
"""

from epicstaff_plugin.contracts.gateway_context import PluginIdentity
from epicstaff_plugin.contracts.service_account_api import (
    MAX_PEOPLE_LOOKUP,
    MAX_USER_ID,
    OrganizationRef,
    PeopleLookupResponse,
    PersonRef,
    PluginPerson,
    ServiceAccountInfo,
)
from rbac.access.bitmask import bitmask_to_actions
from rbac.access.catalog import applicable_actions_for
from rest_framework import serializers

from plugins.access.declared_access import package_declared_access_bits
from plugins.access.people_service import PluginPersonFacts
from plugins.identity.principals import PluginServiceAccountPrincipal
from plugins.models import PluginServiceAccountKey


class PeopleLookupRequestSerializer(serializers.Serializer):
    user_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=MAX_USER_ID),
        min_length=1,
        max_length=MAX_PEOPLE_LOOKUP,
    )

    def validate_user_ids(self, user_ids: list[int]) -> list[int]:
        if len(set(user_ids)) != len(user_ids):
            raise serializers.ValidationError("lists a user id more than once")
        return user_ids


def person_ref(user) -> PersonRef:
    return PersonRef(id=user.pk, email=user.email, name=user.effective_display_name)


def service_account_info(
    key: PluginServiceAccountKey, principal: PluginServiceAccountPrincipal
) -> dict:
    """`ServiceAccountInfo` of the key's service account, as JSON-ready data.

    `key` comes with its grant's organization, plugin and current package, as
    `PluginServiceAccountAuthentication` loads it.
    """
    grant = key.service_account.grant
    package = grant.plugin.current_package
    bits = package_declared_access_bits.get(package)
    return ServiceAccountInfo(
        plugin=PluginIdentity(identifier=grant.plugin.identifier, version=package.version),
        organization=OrganizationRef(id=grant.org_id, name=grant.org.name),
        grant_state=grant.state,
        access={
            resource_type: bitmask_to_actions(mask, applicable_actions_for(resource_type))
            for resource_type, mask in bits.items()
        },
        requests_per_minute=principal.requests_per_minute,
        on_behalf_of=person_ref(principal.person) if principal.person is not None else None,
    ).model_dump(mode="json")


def plugin_person(facts: PluginPersonFacts) -> PluginPerson:
    return PluginPerson(
        user=person_ref(facts.user),
        organization=OrganizationRef(id=facts.organization_id, name=facts.organization_name),
        plugin_permissions=facts.plugin_permissions,
        epicstaff_permissions=facts.epicstaff_permissions,
    )


def people_lookup_response(people: list[PluginPersonFacts]) -> dict:
    return PeopleLookupResponse(people=[plugin_person(facts) for facts in people]).model_dump(
        mode="json"
    )
