"""Issue, persist, and revoke temporary storage credentials.

Three callers share this module: a graph session (one account reused by all
storage-demanding nodes in it), a django "Test run" execution (one
per-execution account, no Session involved), and a realtime chat (one
account reused for the whole voice session). Each mints and persists
synchronously via `_mint_and_persist`, keyed to its own
`TemporaryStorageAccount` FK (`session`/`python_code_result`/
`realtime_agent_chat` -- exactly one set per row, see that model's
`CheckConstraint`). Revocation (`revoke`) is the single place that talks to
the storage backend to delete a service account; callers own the row lookup
and the opportunistic row deletion, since those differ per FK.
"""

import asyncio
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from loguru import logger
from rbac.models import Organization
from src.shared.models.sessions import SessionData
from src.shared.models.storage_scope import StorageCredentials
from tables.models import PythonCodeResult, RealtimeAgentChat, Session

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

    Returns:
        StorageCredentials (access_key, secret_key) if storage is needed,
        None otherwise.

    Raises:
        TemporaryCredentialIssueError: If minting or DB persistence fails.
        Failure here propagates and stops the session startup.
    """
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
    return _mint_and_persist(
        allowed_paths=union_allowed_paths,
        org_id=org.id,
        fk_field="session",
        fk_value=session_orm,
        owner_label=f"session {session_orm.id}",
    )


def issue_for_test_run(
    python_code_result: PythonCodeResult, storage_allowed_paths: list[str], org_id: int
) -> StorageCredentials:
    """Mint and persist temporary storage credentials for a django "Test run"
    execution. Unlike `issue_for_session`, the caller has already determined
    `use_storage=True`, so this always mints (never returns None)."""
    return _mint_and_persist(
        allowed_paths=storage_allowed_paths,
        org_id=org_id,
        fk_field="python_code_result",
        fk_value=python_code_result,
        owner_label=f"test-run {python_code_result.execution_id}",
    )


def issue_for_realtime_chat(
    realtime_agent_chat: RealtimeAgentChat, storage_allowed_paths: list[str], org_id: int
) -> StorageCredentials:
    """Mint and persist temporary storage credentials for a realtime chat
    session. One account for the whole chat, reused by every storage tool
    call within it (mirrors `issue_for_session`'s one-per-session reuse)."""
    return _mint_and_persist(
        allowed_paths=storage_allowed_paths,
        org_id=org_id,
        fk_field="realtime_agent_chat",
        fk_value=realtime_agent_chat,
        owner_label=f"realtime chat {realtime_agent_chat.id}",
    )


def _mint_and_persist(
    *, allowed_paths: list[str], org_id: int, fk_field: str, fk_value, owner_label: str
) -> StorageCredentials:
    """Shared mint + persist body for all three `issue_for_*` entry points.

    Not best-effort: any failure here -- minting or persisting -- raises
    `TemporaryCredentialIssueError`, and the caller's own execution does not
    proceed. A service account that did mint before a DB-write failure is
    never rolled back; it has a native `expiration` (see `expiration` below)
    and will stop authenticating on its own regardless of the missing row.
    """
    policy = build_temporary_policy(
        bucket=settings.STORAGE_BUCKET_NAME, allowed_folders=set(allowed_paths)
    )

    try:
        org_creds = org_credential_store.get(org_id=org_id)
    except Exception as error:
        raise TemporaryCredentialIssueError(
            f"Failed to retrieve org-level storage credentials for org_id={org_id}: {error}"
        ) from error

    ttl_hours = settings.STORAGE_TEMP_CREDENTIALS_TTL_HOURS
    expiration = (
        timedelta(hours=ttl_hours) if ttl_hours > 0 else timedelta(days=36500)
    )  # ~100 years
    try:
        access_key, secret_key = asyncio.run(
            _mint_temporary_service_account(
                org_creds=org_creds, policy=policy, expiration=expiration
            )
        )
    except TemporaryCredentialIssueError:
        raise
    except Exception as error:
        raise TemporaryCredentialIssueError(
            f"Failed to mint temporary storage credentials for {owner_label}: {error}"
        ) from error

    try:
        TemporaryStorageAccount.objects.create(
            access_key=access_key, issued_at=timezone.now(), **{fk_field: fk_value}
        )
        logger.info(
            "Persisted temporary storage account for {} with access_key {}",
            owner_label,
            access_key,
        )
    except Exception as error:
        raise TemporaryCredentialIssueError(
            f"Failed to persist temporary storage account for {owner_label}: {error}"
        ) from error

    return StorageCredentials(access_key=access_key, secret_key=secret_key)


async def _mint_temporary_service_account(
    org_creds, policy: dict, expiration: timedelta
) -> tuple[str, str]:
    """Async helper to mint a temporary service account.

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


def revoke(access_key: str, org_id: int) -> None:
    """Revoke a temporary storage service account. The single place that
    talks to the storage backend to delete one -- callers own the
    TemporaryStorageAccount row lookup and its opportunistic deletion,
    since those differ per FK (session/python_code_result/realtime_agent_chat).

    Raises:
        TemporaryCredentialRevokeError: if the storage backend rejects the
        request, or org_credential_store.get() fails. Callers treat this as
        best-effort -- catch broadly and log, never let it block the caller's
        own completion.
    """
    org_creds = org_credential_store.get(org_id=org_id)
    asyncio.run(_revoke_temporary_service_account(org_creds=org_creds, access_key=access_key))


async def _revoke_temporary_service_account(org_creds, access_key: str) -> None:
    gateway = StorageAdminGateway(
        host=settings.STORAGE_ENDPOINT,
        access_key=org_creds.access_key,
        secret_key=org_creds.secret_key,
    )
    try:
        await gateway.delete_service_account(access_key)
    finally:
        await gateway.close()
