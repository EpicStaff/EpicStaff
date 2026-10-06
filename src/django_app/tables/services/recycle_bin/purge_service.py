"""Remove a recycle-bin item for good."""

from tables.models import SourceCollection
from tables.models.base_models import SoftDeleteMixin
from tables.services.knowledge_services.collection_management_service import (
    CollectionManagementService,
)
from tables.services.recycle_bin.registry import bin_resource_for
from utils.logger import logger


class PurgeService:
    @staticmethod
    def purge(root: SoftDeleteMixin, *, actor: str) -> None:
        """Hard-delete a binned root and everything that cascades from it.

        A collection goes through CollectionManagementService.purge_collection,
        which also drops the document content and GraphRAG data only it used.
        Callers pick `root` from RecycleBinService.binned(); this method doesn't
        apply the bin's org filter itself.

        Every purge is logged with `actor` (who asked for it, e.g. "user 7" or
        "retention job"): it can't be undone, so it must be traceable. The log
        line holds ids only, no names.

        Raises:
            NotInRecycleBinError: `root` is live (e.g. restored after the caller
                loaded it). Purge never removes a live item.
        """
        resource = bin_resource_for(type(root))
        pk = root.pk
        org_id = getattr(root, f"{resource.org_field}_id")
        batch = root.soft_delete_batch

        if isinstance(root, SourceCollection):
            CollectionManagementService.purge_collection(root)
        else:
            root.purge()

        logger.info(
            "Purged {model} {pk} of org {org_id} (batch {batch}) by {actor}",
            model=resource.model.__name__,
            pk=pk,
            org_id=org_id,
            batch=batch,
            actor=actor,
        )
