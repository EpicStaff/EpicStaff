"""Issue, persist, and revoke temporary storage credentials.

Three callers share this module: a graph session (one account reused by all
storage-demanding nodes in it), a django "Test run" execution (one
per-execution account, no Session involved), and a realtime chat (one
account reused for the whole voice session). Each mints and persists
synchronously via `_mint_and_persist`, keyed to its own
`TemporaryStorageAccount` FK (`session`/`python_code_result`/
`realtime_agent_chat` -- exactly one set per row, see that model's
`CheckConstraint`). Revocation mirrors that split: one `revoke_for_*` entry
point per owner type, each resolving the owning organization through its own
FK path and then sharing `_revoke_and_delete`, which is the single place that
talks to the storage backend to delete a service account and drop its row.
"""

import asyncio
from datetime import timedelta

from django.conf import settings
from django.db.models import F
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
from storage_credentials.resource_names import org_storage_prefix
from storage_credentials.services.org_credential_store import org_credential_store
from storage_credentials.services.scope_validator import credential_scope_validator
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
        CredentialScopeValidationError: If the collected scope is missing,
        malformed, or escapes the org's own prefix.
        TemporaryCredentialIssueError: If minting or DB persistence fails.
        Failure here propagates and stops the session startup.
    """
    needs_storage, union_allowed_paths, node_declared_org_prefix = collect_storage_demand(
        session_data
    )

    if not needs_storage:
        logger.info("Session {} does not require storage access", session_orm.id)
        return None

    logger.info(
        "Session {} requires storage access. Paths: {}, node-declared org_prefix: {}",
        session_orm.id,
        union_allowed_paths,
        node_declared_org_prefix,
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
    `use_storage=True`, so this always mints (never returns None).

    Raises:
        CredentialScopeValidationError: If the given scope is missing,
        malformed, or escapes the org's own prefix.
        TemporaryCredentialIssueError: If minting or DB persistence fails.
    """
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
    call within it (mirrors `issue_for_session`'s one-per-session reuse).

    Raises:
        CredentialScopeValidationError: If the given scope is missing,
        malformed, or escapes the org's own prefix.
        TemporaryCredentialIssueError: If minting or DB persistence fails.
    """
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
    never rolled back; with a positive TTL it stops authenticating on its own
    regardless of the missing row, and with `STORAGE_TEMP_CREDENTIALS_TTL_HOURS
    <= 0` it is left to the revocation path and the manager's cleanup job.

    `allowed_paths` are namespaced under the prefix of the org named by
    `org_id` -- the org whose credentials do the minting -- never under a
    prefix declared by the graph data being executed. The two are expected to
    agree; deriving it here is what makes a tampered or stale node-level
    `storage_org_prefix` unable to reach another org's objects.

    Raises:
        CredentialScopeValidationError: `allowed_paths` is empty or escapes
            the org prefix.
        TemporaryCredentialIssueError: minting or persisting failed.
    """
    scoped_folders = credential_scope_validator.validate(
        org_id=org_id,
        storage_org_prefix=org_storage_prefix(org_id),
        storage_allowed_paths=allowed_paths,
    )
    policy = build_temporary_policy(
        bucket=settings.STORAGE_BUCKET_NAME, allowed_folders=scoped_folders
    )

    try:
        org_creds = org_credential_store.get(org_id=org_id)
    except Exception as error:
        raise TemporaryCredentialIssueError(
            f"Failed to retrieve org-level storage credentials for org_id={org_id}: {error}"
        ) from error

    ttl_hours = settings.STORAGE_TEMP_CREDENTIALS_TTL_HOURS
    expiration = timedelta(hours=ttl_hours) if ttl_hours > 0 else None
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
        logger.info("Persisted temporary storage account for {}", owner_label)
    except Exception as error:
        raise TemporaryCredentialIssueError(
            f"Failed to persist temporary storage account for {owner_label}: {error}"
        ) from error

    return StorageCredentials(access_key=access_key, secret_key=secret_key)


async def _mint_temporary_service_account(
    org_creds, policy: dict, expiration: timedelta | None
) -> tuple[str, str]:
    """Async helper to mint a temporary service account.

    A `None` expiration mints a non-expiring account, which only
    `STORAGE_TEMP_CREDENTIALS_TTL_HOURS <= 0` produces.

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


def revoke_for_session(session_id: int) -> None:
    """Revoke the temporary storage account issued for a graph session.

    Best-effort: a session reaching a terminal status must not be held up by
    the storage backend, so nothing here raises. A missing account is a
    no-op -- most sessions never demand storage.

    The owning org is read through `session__graph__org_id` rather than
    `session.graph.org_id`: `Session.graph` is nullable, and attribute access
    on a detached graph raises instead of yielding `None`, which would hide
    the orphaned account behind a generic error.

    Args:
        session_id: Session whose account should be revoked.
    """
    _revoke_and_delete(
        owner_filter={"session_id": session_id},
        org_id_path="session__graph__org_id",
        owner_label=f"session {session_id}",
    )


def revoke_for_test_run(execution_id: str) -> None:
    """Revoke the temporary storage account issued for a django "Test run".

    Best-effort, like `revoke_for_session`: called while persisting the
    execution result, and a revocation failure must not lose that result.

    Args:
        execution_id: `PythonCodeResult.execution_id` of the finished run.
    """
    _revoke_and_delete(
        owner_filter={"python_code_result__execution_id": execution_id},
        org_id_path="python_code_result__org_id",
        owner_label=f"test-run {execution_id}",
    )


def revoke_for_realtime_chat(realtime_agent_chat_id: int) -> None:
    """Revoke the temporary storage account issued for a realtime chat.

    Best-effort, like `revoke_for_session`: called when the realtime service
    reports the call ended, and a revocation failure must not fail that call.

    The chat has no `org` column of its own; it inherits one from the agent
    definition behind its realtime definition.

    Args:
        realtime_agent_chat_id: `RealtimeAgentChat.id` of the ended chat.
    """
    _revoke_and_delete(
        owner_filter={"realtime_agent_chat_id": realtime_agent_chat_id},
        org_id_path="realtime_agent_chat__rt_agent_definition__agent_definition__organization_id",
        owner_label=f"realtime chat {realtime_agent_chat_id}",
    )


def _revoke_and_delete(*, owner_filter: dict, org_id_path: str, owner_label: str) -> None:
    """Shared revoke + delete body for all three `revoke_for_*` entry points.

    Deletes the `TemporaryStorageAccount` row only after the backend confirms
    the service account is gone, so a failed revocation leaves the row for the
    manager's cleanup job to retry.

    `org_id_path` is an ORM lookup from `TemporaryStorageAccount` to the owning
    organization. It is resolved in the same query as the row via `F()`, so a
    broken ownership chain yields `None` instead of raising on attribute
    access.

    Every failure is swallowed and logged: all three callers run on a
    completion path where the owner's own work is already done, and
    `StorageAdminGateway` already classifies backend errors.
    """
    try:
        account = (
            TemporaryStorageAccount.objects.filter(**owner_filter)
            .annotate(owner_org_id=F(org_id_path))
            .first()
        )
        if account is None:
            logger.debug("No temporary storage account found for {}", owner_label)
            return

        if account.owner_org_id is None:
            logger.error(
                "Cannot revoke temporary storage account for {}: no owning organization "
                "reachable via {}. Leaving the row for cleanup.",
                owner_label,
                org_id_path,
            )
            return

        revoke(access_key=account.access_key, org_id=account.owner_org_id)
        logger.info("Revoked temporary storage account for {}", owner_label)

        account.delete()
        logger.debug("Deleted temporary storage account record for {}", owner_label)
    except Exception as error:
        logger.warning(
            "Failed to revoke temporary storage credentials for {}: {}", owner_label, error
        )


def revoke(access_key: str, org_id: int) -> None:
    """Revoke a temporary storage service account in the storage backend.

    Talks to the backend only -- it does not touch `TemporaryStorageAccount`.
    Use `_revoke_and_delete` (via a `revoke_for_*` entry point) for the full
    revoke-then-drop-the-row flow.

    Raises:
        OrgStorageCredentialMissingError: if org_credential_store.get() fails.
        TemporaryCredentialRevokeError: if the storage backend rejects the
        request. Callers treat both as best-effort -- catch broadly and log,
        never let it block the caller's own completion.
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
