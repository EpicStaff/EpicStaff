"""Purge the org's storage bin to make room for the writes of a run, when the run may."""

from loguru import logger
from tables.exceptions import StorageQuotaExceeded
from tables.services.storage_service import get_storage_manager
from tables.services.storage_service.dataclasses import BinPurgeGrant
from tables.services.storage_service.quota import purge_bin_to_fit_quota
from tables.services.storage_service.recycle_bin import StorageRecycleBinService

from storage_credentials.models import TemporaryStorageAccount
from storage_credentials.services.acting_identity import ActingIdentity


def may_purge_bin(account: TemporaryStorageAccount, org_id: int) -> bool:
    """Whether the run behind `account` may have the org's storage bin purged right now.

    The mint-time decision on the row must hold, and the user's FILES:DELETE is resolved
    live, so a role changed since the run began counts. A sub-flow whose root session was
    started with an API key never purges.
    """
    if (
        not account.may_purge_storage_bin
        or account.issued_for_user is None
        or account.issued_for_root_api_key_id is not None
    ):
        return False
    root = (
        ActingIdentity(principal=account.issued_for_root_user)
        if account.issued_for_root_user is not None
        else None
    )
    return ActingIdentity(principal=account.issued_for_user, bounded_by=root).may_purge_storage_bin(
        org_id
    )


def purge_bin_for_run(account: TemporaryStorageAccount, org_id: int, run_label: str) -> None:
    """Purge the oldest storage bin entries, just enough to bring the org back under its quota.

    Does nothing unless the run may purge. If the whole bin would not be enough, nothing
    is purged. The purged entries are logged.
    """
    if not may_purge_bin(account, org_id):
        return
    actor = f"user {account.issued_for_user_id} via {run_label}"
    try:
        purged = purge_bin_to_fit_quota(
            org_id,
            recycle_bin=StorageRecycleBinService(get_storage_manager()),
            bin_purge=BinPurgeGrant(actor=actor),
        )
    except StorageQuotaExceeded:
        logger.warning(
            "Purging the whole storage bin of org {} would not bring it under its quota; "
            "nothing purged",
            org_id,
        )
        return
    logger.warning(
        "Purged {} recycle-bin entries of org {} to make room for writes of {}: {}",
        len(purged),
        org_id,
        run_label,
        [(entry.name, entry.size) for entry in purged],
    )
