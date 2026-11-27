import copy
from collections.abc import Callable
from functools import cache

from django.contrib.auth import get_user_model
from django.db import transaction
from utils.logger import logger

from rbac.exceptions import PreferenceSectionNotFoundError
from rbac.models import Organization, OrganizationUser
from rbac.profile.preferences.sections import (
    PREFERENCE_SECTIONS,
    OrgKeyedIdField,
    PreferenceSectionSerializer,
)


class UserPreferencesService:
    """Reads and changes a user's personal preferences (`User.preferences`).

    Preferences are stored sparse, by section, and read as the section defaults merged
    with the stored values. They are the user's own UI choices: changing them records no
    user action and does not touch `updated_at`.
    """

    def effective(self, user) -> dict[str, dict]:
        """Return every registered section, defaults merged with the user's stored values.

        Organization-keyed entries for organizations the user can no longer work in are
        left out of the result, not deleted. Queries the database only when the user has
        such entries stored.
        """
        organization_ids = cache(lambda: self._working_organization_ids(user))
        return {
            section: self._effective_section(
                serializer_class, user.preferences.get(section, {}), organization_ids
            )
            for section, serializer_class in PREFERENCE_SECTIONS.items()
        }

    def patch_section(
        self,
        user,
        section: str,
        data,
        resolve_organization_id: Callable[[], int | None],
    ) -> dict:
        """Validate `data` against the section and merge it into the stored section.

        Only the keys in `data` change. The user row is locked for the read-merge-write,
        so two requests changing different sections (two browser tabs saving at once)
        both survive.

        Args:
            data: The request body; a partial section.
            resolve_organization_id: Returns the caller's active organization, checked
                for membership, or None when the request names none. Called only when
                `data` changes an organization-keyed preference, so a section without
                one saves whatever organization the request names.

        Returns:
            The section's effective value after the change.

        Raises:
            PreferenceSectionNotFoundError: No section is registered under `section`.
            ValidationError: `data` is not a valid partial section; nothing is saved.
            OrgMembershipRequiredError, OrgDeactivatedError: `data` changes an
                organization-keyed preference and the caller may not act in the
                organization the request names.
            OrgContextRequiredError: the same change with a malformed organization header.
            OrganizationNotFoundError: the same change by a superadmin naming an
                organization that does not exist.
        """
        serializer_class = PREFERENCE_SECTIONS.get(section)
        if serializer_class is None:
            raise PreferenceSectionNotFoundError()
        User = get_user_model()  # noqa: N806
        with transaction.atomic():
            locked_user = User.objects.select_for_update().only("pk", "preferences").get(pk=user.pk)
            stored_section = locked_user.preferences.get(section, {})
            serializer = serializer_class(
                data=data,
                partial=True,
                context={
                    "resolve_organization_id": resolve_organization_id,
                    "stored_section": stored_section,
                },
            )
            serializer.is_valid(raise_exception=True)
            changed_section = {**stored_section, **serializer.validated_data}
            locked_user.preferences = {**locked_user.preferences, section: changed_section}
            locked_user.save(update_fields=["preferences"])
        user.preferences = locked_user.preferences
        logger.info(
            "profile.preferences_updated user_id={} section={} keys={}",
            user.pk,
            section,
            sorted(serializer.validated_data),
        )
        return self._effective_section(
            serializer_class,
            changed_section,
            cache(lambda: self._working_organization_ids(user)),
        )

    @staticmethod
    def _effective_section(
        serializer_class: type[PreferenceSectionSerializer],
        stored_section: dict,
        organization_ids: Callable[[], frozenset[int]],
    ) -> dict:
        effective = {}
        for name, field in serializer_class().fields.items():
            value = (
                stored_section[name]
                if name in stored_section
                else copy.deepcopy(field.get_default())
            )
            if isinstance(field, OrgKeyedIdField) and value:
                value = {
                    organization_key: object_id
                    for organization_key, object_id in value.items()
                    if int(organization_key) in organization_ids()
                }
            effective[name] = value
        return effective

    @staticmethod
    def _working_organization_ids(user) -> frozenset[int]:
        """Ids of the active organizations the user can work in: a superadmin's are all of them."""
        if user.is_superadmin:
            organizations = Organization.objects.filter(is_active=True)
            return frozenset(organizations.values_list("pk", flat=True))
        memberships = OrganizationUser.objects.filter(user=user, org__is_active=True)
        return frozenset(memberships.values_list("org_id", flat=True))
