"""Issue and persist temporary storage credentials for a session.

Synchronously mints a service account in the storage backend and records its
access_key in the TemporaryStorageAccount table. Called from run_session()
during session initialization, before the session is published to crew.
"""

import asyncio
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from loguru import logger
from rbac.models import Organization
from src.shared.models.sessions import SessionData
from src.shared.models.storage_scope import StorageCredentials
from tables.models import Session

from storage_credentials.clients.minio_admin_client import StorageAdminGateway
from storage_credentials.exceptions import TemporaryCredentialIssueError
from storage_credentials.models import TemporaryStorageAccount
from storage_credentials.policies import build_temporary_policy
from storage_credentials.services.org_credential_store import org_credential_store
from storage_credentials.services.storage_demand_collector import collect_storage_demand


def issue_for_session(
    session_data: SessionData, session_orm: Session, org: Organization
) -> StorageCredentials | None:
    """Mint and persist temporary storage credentials for a session.

    Traverses the session graph to determine if storage access is needed.
    If yes, mints a temporary service account in the storage backend scoped
    to the union of storage_allowed_paths from all storage-demanding nodes,
    and persists the access_key in TemporaryStorageAccount.

    Args:
        session_data: The session's graph data (with subgraphs).
        session_orm: The Session ORM instance (persisted already).
        org: The organization this session belongs to.

    Returns:
        StorageCredentials (access_key, secret_key) if storage is needed,
        None otherwise.

    Raises:
        TemporaryCredentialIssueError: If minting or DB persistence fails.
        Failure here propagates and stops the session startup.
    """
    # Determine if this session needs storage and collect scope
    needs_storage, union_allowed_paths, org_prefix = collect_storage_demand(session_data)

    if not needs_storage:
        logger.info("Session {} does not require storage access", session_orm.id)
        return None

    logger.info(
        "Session {} requires storage access. Paths: {}, org_prefix: {}",
        session_orm.id,
        union_allowed_paths,
        org_prefix,
    )

    # Build policy scoped to union of allowed paths
    policy = build_temporary_policy(
        bucket=settings.STORAGE_BUCKET_NAME, allowed_folders=set(union_allowed_paths)
    )

    # Get org-level credentials to mint the temporary service account
    try:
        org_creds = org_credential_store.get(org_id=org.id)
    except Exception as error:
        raise TemporaryCredentialIssueError(
            f"Failed to retrieve org-level storage credentials for org_id={org.id}: {error}"
        ) from error

    # Mint temporary service account via StorageAdminGateway
    # Run the async call in an isolated event loop (synchronous context)
    ttl_hours = settings.STORAGE_TEMP_CREDENTIALS_TTL_HOURS
    expiration = (
        timedelta(hours=ttl_hours) if ttl_hours > 0 else timedelta(days=36500)
    )  # ~100 years
    access_key, secret_key = asyncio.run(
        _mint_temporary_service_account(org_creds=org_creds, policy=policy, expiration=expiration)
    )

    # Persist the access_key in the TemporaryStorageAccount table
    # This is NOT best-effort; failure here stops the session startup
    try:
        TemporaryStorageAccount.objects.create(
            session=session_orm, access_key=access_key, issued_at=timezone.now()
        )
        logger.info(
            "Persisted temporary storage account for session {} with access_key {}",
            session_orm.id,
            access_key,
        )
    except Exception as error:
        raise TemporaryCredentialIssueError(
            f"Failed to persist temporary storage account for session_id={session_orm.id}: {error}"
        ) from error

    return StorageCredentials(access_key=access_key, secret_key=secret_key)


async def _mint_temporary_service_account(
    org_creds, policy: dict, expiration: timedelta
) -> tuple[str, str]:
    """Async helper to mint a temporary service account.

    Args:
        org_creds: OrgStorageCredentials with org-level access and secret keys.
        policy: IAM policy dict scoped to allowed_folders.
        expiration: Lifetime of the temporary account (timedelta).

    Returns:
        Tuple of (access_key, secret_key).

    Raises:
        TemporaryCredentialIssueError: If the storage backend rejects the request.
    """
    gateway = StorageAdminGateway(
        host=settings.STORAGE_ENDPOINT,
        access_key=org_creds.access_key,
        secret_key=org_creds.secret_key,
    )
    try:
        access_key, secret_key = await gateway.create_service_account(
            policy=policy, expiration=expiration
        )
        return access_key, secret_key
    finally:
        # Explicitly close the gateway and its aiohttp session to prevent
        # connection pool leaks when the event loop exits.
        await gateway.close()
