from typing import Any

from django.db import transaction
from loguru import logger
from src.shared.retention import DataType

from rbac.exceptions import OrganizationNotFoundError
from rbac.governance.cross_org_base import CrossOrgResourceService
from rbac.models import Organization, OrganizationRetention
from rbac.models.enums import Permission, ResourceType
from rbac.validation.organization_retention import OrganizationRetentionValidationService


def effective_retention_days_for_org(org_id: int, data_type: DataType) -> int:
    """Return how many days `data_type` is kept for the organization; 0 means forever.

    For Django callers. An organization without a retention row gets the instance
    default. Does not authorize; the caller must already be allowed to act on `org_id`.
    """
    retention = OrganizationRetention.objects.filter(org_id=org_id).first()
    return (retention or OrganizationRetention(org_id=org_id)).effective_days(data_type)


class OrganizationRetentionService(CrossOrgResourceService):
    """Read and change an organization's retention choices from the admin surface.

    Authorized with the ORGANIZATIONS bits in the target organization, the same way
    `OrganizationManagementService` authorizes a rename: an organization the actor
    cannot see raises OrganizationNotFoundError (404), a visible one without the bit
    raises PermissionDenied (403).
    """

    rbac_resource_type = ResourceType.ORGANIZATIONS
    not_found_exception = OrganizationNotFoundError

    _validator = OrganizationRetentionValidationService()

    def get_retention(self, actor, org_id: int) -> OrganizationRetention:
        """Return the organization's retention, unsaved and empty when it has never changed it."""
        effective = self.resolve_for_write(actor, org_id, action=Permission.READ)
        self.assert_can(effective, Permission.READ)
        # For members the resolver already found the active organization; a superadmin
        # skips that lookup, so only their request can name a missing one.
        if effective.is_superadmin and not Organization.objects.filter(pk=org_id).exists():
            raise OrganizationNotFoundError()
        retention = (
            OrganizationRetention.objects.select_related("updated_by").filter(org_id=org_id).first()
        )
        return retention or OrganizationRetention(org_id=org_id)

    @transaction.atomic
    def update_retention(self, actor, org_id: int, data: Any) -> OrganizationRetention:
        """Validate the sent retention choices, store them and stamp `actor` as the last editor.

        Validation runs here, under the row locks, because a value equal to the stored
        one is accepted even above a lowered cap, and that comparison needs the stored
        row a concurrent update cannot change underneath it.

        Args:
            data: The raw PATCH body. Unsent types are left unchanged; null resets a type
                to the instance default.

        Raises:
            FormValidationError: A value is neither null, allowed by the policy, nor the
                stored one, or no retention field was sent.
        """
        effective = self.resolve_for_write(actor, org_id, action=Permission.UPDATE)
        self.assert_can(effective, Permission.UPDATE)
        # The lock makes a concurrent organization delete wait, so the insert below
        # cannot fail on a vanished foreign key.
        locked_org_id = (
            Organization.objects.select_for_update(no_key=True)
            .filter(pk=org_id)
            .values_list("pk", flat=True)
            .first()
        )
        if locked_org_id is None:
            raise OrganizationNotFoundError()
        retention = OrganizationRetention.objects.select_for_update().filter(org_id=org_id).first()
        values = self._validator.validate_update(
            data, retention or OrganizationRetention(org_id=org_id)
        )
        fields = {
            OrganizationRetention.FIELD_BY_DATA_TYPE[data_type]: days
            for data_type, days in values.items()
        }
        if retention is None:
            retention = OrganizationRetention.objects.create(
                org_id=org_id, updated_by=actor, **fields
            )
        else:
            for field_name, days in fields.items():
                setattr(retention, field_name, days)
            retention.updated_by = actor
            retention.save()
        logger.info(
            "Organization retention updated org_id={} actor_id={} values={}",
            org_id,
            actor.pk,
            fields,
        )
        return retention
