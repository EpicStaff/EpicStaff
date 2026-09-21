from loguru import logger

from tables.models.base_models import DefaultBaseModel
from tables.models.rbac_models import Organization
from tables.services.rbac.delete.strategy import DeleteStrategy
from tables.services.rbac.rbac_exceptions import (
    DefaultOrganizationNotDeletableError,
    LastOrganizationError,
    OrganizationNotFoundError,
)
from tables.services.storage_service import get_storage_backend


class OrganizationDeleteStrategy(DeleteStrategy):
    """Permanent delete of an organization and everything it owns."""

    target_type = "organization"

    def get_instance(self, target_id: int):
        """Load the organization, or raise 404."""
        try:
            return Organization.objects.get(pk=target_id)
        except Organization.DoesNotExist as exc:
            raise OrganizationNotFoundError() from exc

    def validate(self, instance, *, actor) -> None:
        """Refuse the default organization and the last remaining one."""
        if instance.is_default:
            raise DefaultOrganizationNotDeletableError()
        if not Organization.objects.exclude(pk=instance.pk).exists():
            raise LastOrganizationError()

    def validate_locked(self, instance, *, actor) -> None:
        """Re-check both organization guards while holding a lock on every organization row."""
        locked = {
            org.pk: org
            for org in Organization.objects.order_by("pk").select_for_update()
        }
        target = locked.get(instance.pk)
        if target is not None and target.is_default:
            raise DefaultOrganizationNotDeletableError()
        if not set(locked) - {instance.pk}:
            raise LastOrganizationError()

    def describe(self, instance) -> dict:
        """Return the organization's identity for the report."""
        return {
            "type": self.target_type,
            "id": instance.pk,
            "name": instance.name,
        }

    @staticmethod
    def _storage_prefix(instance) -> str:
        """Return the MinIO key prefix owning this organization's objects."""
        return f"org_{instance.pk}/"

    def external_artifacts(self, instance) -> list[dict]:
        """Count and size the MinIO objects this delete would orphan."""
        prefix = self._storage_prefix(instance)
        try:
            backend = get_storage_backend(organization_prefix=prefix)
            objects = backend.list_all_objects("")
        except Exception as exc:
            logger.warning(
                "delete.storage_preview_failed org_id={} error={}",
                instance.pk,
                exc,
            )
            return [
                {
                    "kind": "object_storage",
                    "prefix": prefix,
                    "objects": None,
                    "bytes": None,
                }
            ]
        return [
            {
                "kind": "object_storage",
                "prefix": prefix,
                "objects": len(objects),
                "bytes": sum(entry[1] for entry in objects),
            }
        ]

    def snapshot(self, instance) -> dict:
        """Capture the storage prefix before the organization row disappears."""
        return {"storage_prefix": self._storage_prefix(instance)}

    def cleanup_external(self, snapshot: dict) -> None:
        """Reset the platform default cache and purge every MinIO object under the organization's prefix."""
        # The cascade nulls Default* singleton FKs with a raw UPDATE, which the
        # process-level cache in DefaultBaseModel.save() never sees.
        DefaultBaseModel._load_cache.clear()
        backend = get_storage_backend(organization_prefix=snapshot["storage_prefix"])
        backend.delete_prefix("")
