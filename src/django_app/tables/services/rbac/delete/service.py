from django.db import transaction
from loguru import logger

from tables.services.rbac.delete.collector import collect_deletion_report
from tables.services.rbac.delete.organization_strategy import (
    OrganizationDeleteStrategy,
)
from tables.services.rbac.delete.strategy import DeleteStrategy
from tables.services.rbac.delete.user_strategy import UserDeleteStrategy


class DeleteService:
    """Permanently deletes a user or an organization, with a dry-run preview."""

    def __init__(self):
        self._strategies = {
            "user": UserDeleteStrategy,
            "organization": OrganizationDeleteStrategy,
        }

    def delete(self, *, target_type: str, target_id: int, actor, dry_run: bool) -> dict:
        """Report or perform the permanent deletion of one target."""
        strategy = self._strategies[target_type]()
        instance = strategy.get_instance(target_id)
        strategy.validate(instance, actor=actor)

        report = collect_deletion_report(instance)
        payload = {
            "dry_run": dry_run,
            "target": strategy.describe(instance),
            "database": {
                "total": report["total"],
                "by_model": report["by_model"],
            },
            "field_updates": report["field_updates"],
            "external": strategy.external_artifacts(instance),
        }
        if dry_run:
            logger.info(
                "delete.previewed actor={} target_type={} target_id={} rows={}",
                getattr(actor, "email", "system"),
                target_type,
                target_id,
                report["total"],
            )
            return payload

        # Captured before the delete: after it, the row these read from is gone.
        snapshot = strategy.snapshot(instance)
        with transaction.atomic():
            # The unlocked validate() above can be raced by a concurrent delete;
            # this re-check holds a lock on the contested rows until commit.
            strategy.validate_locked(instance, actor=actor)
            strategy.pre_delete(instance)
            instance.delete()
            transaction.on_commit(lambda: self._cleanup_external(strategy, snapshot))
        logger.info(
            "delete.completed actor={} target_type={} target_id={} rows={}",
            getattr(actor, "email", "system"),
            target_type,
            target_id,
            report["total"],
        )
        return payload

    @staticmethod
    def _cleanup_external(strategy: DeleteStrategy, snapshot: dict) -> None:
        """Best-effort external cleanup that must never fail a committed delete."""
        try:
            strategy.cleanup_external(snapshot)
        except Exception as exc:
            logger.error(
                "delete.external_cleanup_failed target_type={} error={}",
                strategy.target_type,
                exc,
            )
