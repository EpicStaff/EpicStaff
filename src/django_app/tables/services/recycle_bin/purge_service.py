"""Remove a recycle-bin item for good."""

from tables.models import SourceCollection
from tables.models.base_models import SoftDeleteMixin
from tables.services.knowledge_services.collection_management_service import (
    CollectionManagementService,
)


class PurgeService:
    @staticmethod
    def purge(root: SoftDeleteMixin) -> None:
        """Hard-delete a binned root and everything that cascades from it.

        A collection goes through CollectionManagementService.purge_collection,
        which also drops the document content and GraphRAG data only it used.
        Callers pick `root` from RecycleBinService.binned(); this method doesn't
        apply the bin's org filter itself.

        Raises:
            NotInRecycleBinError: `root` is live (e.g. restored after the caller
                loaded it). Purge never removes a live item.
        """
        if isinstance(root, SourceCollection):
            CollectionManagementService.purge_collection(root)
            return
        root.purge()
