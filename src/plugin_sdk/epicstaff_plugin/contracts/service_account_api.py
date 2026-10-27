"""Service account API version 1: what a plugin backend learns from EpicStaff about itself and people.

A plugin backend calls EpicStaff with the service-account key the runtime file holds for an
organization (`Authorization: PluginKey <key>`, `X-Organization-Id: <org id>`). Besides
EpicStaff's ordinary API, which the plugin's declared access caps, three endpoints under
`/api/plugin-runtime/` answer with the documents below:

    GET  /api/plugin-runtime/me/                 -> ServiceAccountInfo
    GET  /api/plugin-runtime/people/{user_id}/   -> PluginPerson (404 person_not_found)
    POST /api/plugin-runtime/people/lookup/      PeopleLookupRequest -> PeopleLookupResponse

A person appears only while they may use the plugin: an active user, an active member of the
organization, which is active, holding the plugin's `read` action under an active grant.
Everyone else is "not found", members without `read` included, so a plugin never learns about
people who cannot use it. A plugin may cache a person for at most 30 seconds.

Every model forbids unknown fields, so the side that builds a document cannot misspell one.
The side that reads one parses it leniently, so a newer EpicStaff that adds a field does not
break a plugin built against an older SDK:

    PluginPerson.model_validate_json(raw, extra="ignore")
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, StringConstraints, field_validator

from epicstaff_plugin.contracts.gateway_context import (
    ContextOrganization,
    ContextUser,
    PluginIdentity,
)
from epicstaff_plugin.contracts.manifest import READ_ACTION, RESOURCE_TYPE_PATTERN, Action

ON_BEHALF_OF_HEADER = "X-EpicStaff-On-Behalf-Of"
SERVICE_ACCOUNT_AUTHORIZATION_SCHEME = "PluginKey"
ORGANIZATION_HEADER = "X-Organization-Id"
MAX_PEOPLE_LOOKUP = 100
# The largest id a person can have: EpicStaff's ids are signed 64-bit integers.
MAX_USER_ID = 2**63 - 1
PERSON_CACHE_MAX_SECONDS = 30

ResourceType = Annotated[str, StringConstraints(pattern=RESOURCE_TYPE_PATTERN)]
UserId = Annotated[int, Field(gt=0, le=MAX_USER_ID)]


class _ServiceAccountContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PersonRef(ContextUser):
    """A person, as a gateway context names them: id, email and display name."""


class OrganizationRef(ContextOrganization):
    """An organization: id and name."""


class ServiceAccountInfo(_ServiceAccountContractModel):
    """The service account a key belongs to, from `GET /api/plugin-runtime/me/`."""

    plugin: PluginIdentity
    organization: OrganizationRef
    grant_state: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    """The grant's state: `granting` while the install hook runs, `active` after it, and
    `upgrading` while the organization's upgrade hook runs. Read as text: a newer EpicStaff may
    add states."""

    access: dict[ResourceType, list[Action]]
    """The plugin's declared access: resource type to actions, in EpicStaff's catalog order."""

    requests_per_minute: PositiveInt
    """How many requests the service account may make per minute before it gets 429."""

    on_behalf_of: PersonRef | None
    """The person `X-EpicStaff-On-Behalf-Of` named, after EpicStaff checked they may use the
    plugin; null without the header."""


class PluginPerson(_ServiceAccountContractModel):
    """A person who may use the plugin in the service account's organization, and their rights.

    `plugin_permissions` are the plugin actions the person holds (the gateway context's
    `permissions`), in manifest order and always with `read`. `epicstaff_permissions` are the
    person's own EpicStaff rights from their membership role, in the shape of EpicStaff's
    `GET /api/permissions/me/` `permissions`: every resource type of the catalog is a key, with
    the actions the role gives, possibly none. EpicStaff never checks them on the plugin's
    calls; a plugin acting for a person checks them itself before it does something the person
    could not do in EpicStaff.
    """

    user: PersonRef
    organization: OrganizationRef
    plugin_permissions: list[Action]
    epicstaff_permissions: dict[ResourceType, list[str]]

    @field_validator("plugin_permissions")
    @classmethod
    def _distinct_with_read(cls, actions: list[str]) -> list[str]:
        if len(set(actions)) != len(actions):
            raise ValueError("lists an action more than once")
        if READ_ACTION not in actions:
            raise ValueError("must include read: only people with read appear")
        return actions

    def has_plugin_permission(self, action: Action) -> bool:
        """Whether the person holds this plugin action."""
        return action in self.plugin_permissions

    def has_epicstaff_permission(self, resource_type: str, action: str) -> bool:
        """Whether the person's own EpicStaff role gives `action` on `resource_type`."""
        return action in self.epicstaff_permissions.get(resource_type, ())


class PeopleLookupRequest(_ServiceAccountContractModel):
    """The body of `POST /api/plugin-runtime/people/lookup/`: 1 to 100 distinct user ids."""

    user_ids: Annotated[list[UserId], Field(min_length=1, max_length=MAX_PEOPLE_LOOKUP)]

    @field_validator("user_ids")
    @classmethod
    def _distinct(cls, user_ids: list[int]) -> list[int]:
        if len(set(user_ids)) != len(user_ids):
            raise ValueError("lists a user id more than once")
        return user_ids


class PeopleLookupResponse(_ServiceAccountContractModel):
    """The people of a lookup who may use the plugin, sorted by user id; the others are left out."""

    people: list[PluginPerson]

    @field_validator("people")
    @classmethod
    def _sorted_by_user_id(cls, people: list[PluginPerson]) -> list[PluginPerson]:
        user_ids = [person.user.id for person in people]
        if user_ids != sorted(set(user_ids)):
            raise ValueError("must list each person once, sorted by user id")
        return people

    def by_user_id(self) -> dict[int, PluginPerson]:
        return {person.user.id: person for person in self.people}


def on_behalf_of_header_value(user_id: int) -> str:
    """Return the `X-EpicStaff-On-Behalf-Of` value for a person.

    Raises:
        ValueError: `user_id` is not a positive integer below 2^63.
    """
    if isinstance(user_id, bool) or not isinstance(user_id, int) or not 0 < user_id <= MAX_USER_ID:
        raise ValueError(f"a user id is a positive integer below 2^63, not {user_id!r}")
    return str(user_id)
