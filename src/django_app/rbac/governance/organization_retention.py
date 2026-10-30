from typing import Any

from django.db import transaction
from django.utils import timezone
from loguru import logger
from src.shared.retention import DataType

from rbac.exceptions import OrganizationNotFoundError
from rbac.governance.cross_org_base import CrossOrgResourceService
from rbac.models import OrganizationConfig
from rbac.models.enums import Permission, ResourceType
from rbac.validation.organization_retention import OrganizationRetentionValidationService


def effective_retention_days_for_org(org_id: int, data_type: DataType) -> int:
    """Return how many days `data_type` is kept for the organization; 0 means forever.

    For Django callers. Does not authorize; the caller must already be allowed to act on
    `org_id`.
    """
    # Called on every session start, which must never fail over settings: an organization
    # without a config row (test fixtures create them) runs with the instance defaults.
    config = OrganizationConfig.objects.filter(org_id=org_id).first()
    return (config or OrganizationConfig(org_id=org_id)).effective_retention_days(data_type)


class OrganizationRetentionService(CrossOrgResourceService):
    """Read and change an organization's retention choices from the admin surface.

    The choices live on the organization's OrganizationConfig row. Authorized with the
    ORGANIZATIONS bits in the target organization, the same way
    `OrganizationManagementService` authorizes a rename: an organization the actor cannot
    see raises OrganizationNotFoundError (404), a visible one without the bit raises
    PermissionDenied (403).
    """

    rbac_resource_type = ResourceType.ORGANIZATIONS
    not_found_exception = OrganizationNotFoundError

    _validator = OrganizationRetentionValidationService()

    def get_retention(self, actor, org_id: int) -> OrganizationConfig:
        """Return the organization's config, which carries its retention choices.

        Raises:
            OrganizationNotFoundError: The organization does not exist (a superadmin skips
                the resolver's lookup, so only their request can name one) or has no config.
        """
        effective = self.resolve_for_write(actor, org_id, action=Permission.READ)
        self.assert_can(effective, Permission.READ)
        config = (
            OrganizationConfig.objects.select_related("retention_updated_by")
            .filter(org_id=org_id)
            .first()
        )
        if config is None:
            raise OrganizationNotFoundError()
        return config

    @transaction.atomic
    def update_retention(self, actor, org_id: int, data: Any) -> OrganizationConfig:
        """Validate the sent retention choices, store them and stamp `actor` as the last editor.

        Validation runs here, under the row lock, because a value equal to the stored one
        is accepted even outside a changed cap or floor, and that comparison needs the
        stored row a concurrent update cannot change underneath it.

        Args:
            data: The raw PATCH body. Unsent types are left unchanged; null resets a type
                to the instance default.

        Raises:
            OrganizationNotFoundError: The organization does not exist or has no config.
            FormValidationError: A value is neither null, allowed by the policy, nor the
                stored one, or no retention field was sent.
        """
        effective = self.resolve_for_write(actor, org_id, action=Permission.UPDATE)
        self.assert_can(effective, Permission.UPDATE)
        config = OrganizationConfig.objects.select_for_update().filter(org_id=org_id).first()
        if config is None:
            raise OrganizationNotFoundError()
        values = self._validator.validate_update(data, config)
        fields = {
            OrganizationConfig.RETENTION_FIELD_BY_DATA_TYPE[data_type]: days
            for data_type, days in values.items()
        }
        for field_name, days in fields.items():
            setattr(config, field_name, days)
        config.retention_updated_at = timezone.now()
        config.retention_updated_by = actor
        config.save(update_fields=[*fields, "retention_updated_at", "retention_updated_by"])
        logger.info(
            "Organization retention updated org_id={} actor_id={} values={}",
            org_id,
            actor.pk,
            fields,
        )
        return config
