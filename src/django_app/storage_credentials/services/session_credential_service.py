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
A fourth entry point, `revoke_for_identity`, revokes by who the accounts were
issued for rather than by owner: it finds many accounts at once and deletes them
in one storage connection per organization (`_revoke_accounts`).
"""

import asyncio
from collections import defaultdict
from collections.abc import Iterable
from datetime import timedelta

from django.conf import settings
from django.db.models import F, Q
from django.db.models.functions import Coalesce
from django.utils import timezone
from loguru import logger
from rbac.models import Organization
from src.shared.models.sessions import SessionData
from src.shared.models.storage_scope import StorageAction, StorageCredentials
from tables.models import PythonCodeResult, RealtimeAgentChat, Session

from storage_credentials.clients.minio_admin_client import StorageAdminGateway
from storage_credentials.exceptions import (
    CredentialScopeValidationError,
    TemporaryCredentialIssueError,
)
from storage_credentials.models import TemporaryStorageAccount
from storage_credentials.policies import build_temporary_policy
from storage_credentials.resource_names import org_storage_prefix
from storage_credentials.services.acting_identity import ActingIdentity
from storage_credentials.services.org_credential_store import org_credential_store
from storage_credentials.services.scope_validator import credential_scope_validator
from storage_credentials.services.storage_demand_collector import collect_storage_demand


class SessionCredentialService:
    """Service for processing temporary storage credentials."""

    def issue_for_session(
        self,
        session_data: SessionData,
        session_orm: Session,
        org: Organization,
        *,
        acting_identity: ActingIdentity,
    ) -> StorageCredentials | None:
        """Mint and persist temporary storage credentials for a session.

        Traverses the session graph to determine if storage access is needed.
        If yes, mints a temporary service account in the storage backend scoped
        to the union of storage_allowed_paths from all storage-demanding nodes,
        and persists the access_key in TemporaryStorageAccount. The session's own
        folder (`sessions/<id>/`) allows every action; the other paths allow only
        what `acting_identity` may do to files (see `_mint_and_persist`).

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
        return self._mint_and_persist(
            allowed_paths=union_allowed_paths,
            org_id=org.id,
            fk_field="session",
            fk_value=session_orm,
            owner_label=f"session {session_orm.id}",
            own_paths=[f"sessions/{session_orm.id}/"],
            acting_identity=acting_identity,
        )

    def issue_for_test_run(
        self,
        python_code_result: PythonCodeResult,
        storage_allowed_paths: list[str],
        org_id: int,
        *,
        own_paths: list[str],
        acting_identity: ActingIdentity,
    ) -> StorageCredentials:
        """Mint and persist temporary storage credentials for a django "Test run"
        execution. Unlike `issue_for_session`, the caller has already determined
        `use_storage=True`, so this always mints (never returns None).

        Raises:
            CredentialScopeValidationError: If the given scope is missing,
            malformed, or escapes the org's own prefix.
            TemporaryCredentialIssueError: If minting or DB persistence fails.
        """
        return self._mint_and_persist(
            allowed_paths=storage_allowed_paths,
            org_id=org_id,
            fk_field="python_code_result",
            fk_value=python_code_result,
            owner_label=f"test-run {python_code_result.execution_id}",
            own_paths=own_paths,
            acting_identity=acting_identity,
        )

    def issue_for_realtime_chat(
        self,
        realtime_agent_chat: RealtimeAgentChat,
        storage_allowed_paths: list[str],
        org_id: int,
        *,
        acting_identity: ActingIdentity,
    ) -> StorageCredentials:
        """Mint and persist temporary storage credentials for a realtime chat
        session. One account for the whole chat, reused by every storage tool
        call within it (mirrors `issue_for_session`'s one-per-session reuse).

        Raises:
            CredentialScopeValidationError: If the given scope is missing,
            malformed, escapes the org's own prefix, or the acting identity may
            not read any of the files the agent's tools use.
            TemporaryCredentialIssueError: If minting or DB persistence fails.
        """
        return self._mint_and_persist(
            allowed_paths=storage_allowed_paths,
            org_id=org_id,
            fk_field="realtime_agent_chat",
            fk_value=realtime_agent_chat,
            owner_label=f"realtime chat {realtime_agent_chat.id}",
            own_paths=[],
            acting_identity=acting_identity,
        )

    def _mint_and_persist(
        self,
        *,
        allowed_paths: list[str],
        org_id: int,
        fk_field: str,
        fk_value,
        owner_label: str,
        own_paths: list[str],
        acting_identity: ActingIdentity,
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

        `own_paths` are the run's own folders, computed by the caller and never read
        from node data; they always allow every action. The rest of `allowed_paths`
        allow what `acting_identity` may do to files in the org. Without READ on
        them they are left out of the account, and the run still gets its own
        folders. The identity is recorded on the row so the account can be revoked
        when that identity's access changes.

        Raises:
            CredentialScopeValidationError: `allowed_paths` is empty or escapes
                the org prefix, or nothing is left to grant because the identity may
                not read the shared folders and the run has no folder of its own.
            TemporaryPolicyTooLargeError: too many files are attached for one policy.
            TemporaryCredentialIssueError: minting or persisting failed.
        """
        scoped_folders = credential_scope_validator.validate(
            org_id=org_id,
            storage_org_prefix=org_storage_prefix(org_id),
            storage_allowed_paths=allowed_paths,
            own_paths=own_paths,
        )
        shared_actions = acting_identity.shared_actions(org_id)
        shared_folders = scoped_folders.shared
        if StorageAction.READ not in shared_actions:
            logger.info(
                "Dropping {} shared storage folder(s) for {}: the acting identity has no "
                "FILES read access",
                len(shared_folders),
                owner_label,
            )
            shared_folders = frozenset()
            shared_actions = frozenset()
        if not shared_folders and not scoped_folders.own:
            raise CredentialScopeValidationError(
                "You don't have access to the files this agent's tools use."
            )
        policy = build_temporary_policy(
            bucket=settings.STORAGE_BUCKET_NAME,
            shared_folders=set(shared_folders),
            shared_actions=shared_actions,
            own_folders=set(scoped_folders.own),
        )

        try:
            org_creds = org_credential_store.get(org_id=org_id)
        except Exception as error:
            logger.exception(
                "Failed to retrieve org-level storage credentials for org_id={}: {}",
                org_id,
                error,
            )
            raise TemporaryCredentialIssueError() from error

        ttl_hours = settings.STORAGE_TEMP_CREDENTIALS_TTL_HOURS
        expiration = timedelta(hours=ttl_hours) if ttl_hours > 0 else None
        try:
            access_key, secret_key = asyncio.run(
                self._mint_temporary_service_account(
                    org_creds=org_creds, policy=policy, expiration=expiration
                )
            )
        except TemporaryCredentialIssueError:
            raise
        except Exception as error:
            logger.exception(
                "Failed to mint temporary storage credentials for {}: {}",
                owner_label,
                error,
            )
            raise TemporaryCredentialIssueError() from error

        root_identity = acting_identity.bounded_by
        try:
            TemporaryStorageAccount.objects.create(
                access_key=access_key,
                issued_at=timezone.now(),
                issued_for_user=acting_identity.recorded_user,
                issued_for_api_key=acting_identity.api_key,
                issued_for_root_user=root_identity.recorded_user if root_identity else None,
                issued_for_root_api_key=root_identity.api_key if root_identity else None,
                **{fk_field: fk_value},
            )
            logger.info("Persisted temporary storage account for {}", owner_label)
        except Exception as error:
            logger.exception(
                "Failed to persist temporary storage account for {}: {}",
                owner_label,
                error,
            )
            raise TemporaryCredentialIssueError() from error

        return StorageCredentials(
            access_key=access_key,
            secret_key=secret_key,
            shared_actions=[action for action in StorageAction if action in shared_actions],
            own_paths=sorted(own_paths),
        )

    async def _mint_temporary_service_account(
        self, org_creds, policy: dict, expiration: timedelta | None
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

    def revoke_for_session(self, session_id: int) -> None:
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
        self._revoke_and_delete(
            owner_filter={"session_id": session_id},
            org_id_path="session__graph__org_id",
            owner_label=f"session {session_id}",
        )

    def revoke_for_test_run(self, execution_id: str) -> None:
        """Revoke the temporary storage account issued for a django "Test run".

        Best-effort, like `revoke_for_session`: called while persisting the
        execution result, and a revocation failure must not lose that result.

        Args:
            execution_id: `PythonCodeResult.execution_id` of the finished run.
        """
        self._revoke_and_delete(
            owner_filter={"python_code_result__execution_id": execution_id},
            org_id_path="python_code_result__org_id",
            owner_label=f"test-run {execution_id}",
        )

    def revoke_for_realtime_chat(self, realtime_agent_chat_id: int) -> None:
        """Revoke the temporary storage account issued for a realtime chat.

        Best-effort, like `revoke_for_session`: called when the realtime service
        reports the call ended, and a revocation failure must not fail that call.

        The chat has no `org` column of its own; it inherits one from the agent
        definition behind its realtime definition.

        Args:
            realtime_agent_chat_id: `RealtimeAgentChat.id` of the ended chat.
        """
        self._revoke_and_delete(
            owner_filter={"realtime_agent_chat_id": realtime_agent_chat_id},
            org_id_path="realtime_agent_chat__rt_agent_definition__agent_definition__org_id",
            owner_label=f"realtime chat {realtime_agent_chat_id}",
        )

    def access_keys_for_identity(
        self,
        *,
        org_id: int | None,
        user_ids: Iterable[int] = (),
        api_key_ids: Iterable[int] = (),
    ) -> list[str]:
        """Access keys of the accounts issued for these users or API keys.

        Includes a sub-flow's account when the user or key started its root session.
        `org_id=None` matches accounts of every organization.
        """
        return [
            access_key
            for access_key, _ in self._accounts_for_identity(
                org_id=org_id, user_ids=user_ids, api_key_ids=api_key_ids
            )
        ]

    def revoke_for_identity(
        self,
        *,
        org_id: int | None,
        user_ids: Iterable[int] = (),
        api_key_ids: Iterable[int] = (),
    ) -> None:
        """Revoke the accounts issued for these users or API keys.

        Called when the access of an identity changes (role, membership, key
        revoked or deleted, user deactivated), so a run in flight stops holding
        credentials built from the old permissions. `org_id=None` covers every
        organization. Best-effort like the other `revoke_for_*` entry points: a
        failure is logged and leaves the row for the manager's cleanup job.
        """
        try:
            accounts = self._accounts_for_identity(
                org_id=org_id, user_ids=user_ids, api_key_ids=api_key_ids
            )
        except Exception as error:
            logger.warning("Failed to look up temporary storage accounts to revoke: {}", error)
            return
        self._revoke_accounts(accounts)

    def revoke_access_keys(self, access_keys: Iterable[str]) -> None:
        """Revoke and delete the accounts with these access keys (best-effort)."""
        try:
            accounts = list(
                TemporaryStorageAccount.objects.filter(access_key__in=list(access_keys))
                .annotate(owner_org_id=self._owner_org_id())
                .values_list("access_key", "owner_org_id")
            )
        except Exception as error:
            logger.warning("Failed to look up temporary storage accounts to revoke: {}", error)
            return
        self._revoke_accounts(accounts)

    def _accounts_for_identity(
        self,
        *,
        org_id: int | None,
        user_ids: Iterable[int],
        api_key_ids: Iterable[int],
    ) -> list[tuple[str, int | None]]:
        """(access key, owning org id) of every account issued for these identities, in one query."""
        user_ids = list(user_ids)
        api_key_ids = list(api_key_ids)
        if not user_ids and not api_key_ids:
            return []
        accounts = TemporaryStorageAccount.objects.filter(
            Q(issued_for_user_id__in=user_ids)
            | Q(issued_for_api_key_id__in=api_key_ids)
            | Q(issued_for_root_user_id__in=user_ids)
            | Q(issued_for_root_api_key_id__in=api_key_ids)
        ).annotate(owner_org_id=self._owner_org_id())
        if org_id is not None:
            accounts = accounts.filter(owner_org_id=org_id)
        return list(accounts.values_list("access_key", "owner_org_id"))

    def _revoke_accounts(self, accounts: list[tuple[str, int | None]]) -> None:
        """Revoke many accounts with one credential fetch and one storage connection per org.

        Deletes a `TemporaryStorageAccount` row only for an account the backend
        confirmed gone, so a failed revocation leaves just that row for the manager's
        cleanup job. Best-effort: every failure is logged, none is raised.

        Args:
            accounts: (access key, id of the org that owns the account). An account
                whose org cannot be resolved is left for the cleanup job.
        """
        access_keys_by_org: dict[int, list[str]] = defaultdict(list)
        for access_key, owner_org_id in accounts:
            if owner_org_id is None:
                logger.error(
                    "Cannot revoke temporary storage account {}: no owning organization "
                    "reachable. Leaving the row for cleanup.",
                    access_key,
                )
                continue
            access_keys_by_org[owner_org_id].append(access_key)

        for org_id, access_keys in access_keys_by_org.items():
            try:
                org_creds = org_credential_store.get(org_id=org_id)
                revoked = asyncio.run(
                    self._delete_service_accounts(org_creds=org_creds, access_keys=access_keys)
                )
                TemporaryStorageAccount.objects.filter(access_key__in=revoked).delete()
            except Exception as error:
                logger.warning(
                    "Failed to revoke temporary storage credentials in org {}: {}", org_id, error
                )

    async def _delete_service_accounts(self, org_creds, access_keys: list[str]) -> list[str]:
        """Delete service accounts on one gateway; returns the access keys confirmed gone."""
        gateway = StorageAdminGateway(
            host=settings.STORAGE_ENDPOINT,
            access_key=org_creds.access_key,
            secret_key=org_creds.secret_key,
        )
        revoked: list[str] = []
        try:
            for access_key in access_keys:
                try:
                    await gateway.delete_service_account(access_key)
                except Exception as error:
                    logger.warning(
                        "Failed to revoke temporary storage account {}: {}", access_key, error
                    )
                    continue
                revoked.append(access_key)
            return revoked
        finally:
            await gateway.close()

    @staticmethod
    def _owner_org_id():
        return Coalesce(
            F("session__graph__org_id"),
            F("python_code_result__org_id"),
            F("realtime_agent_chat__rt_agent_definition__agent_definition__org_id"),
        )

    def _revoke_and_delete(self, *, owner_filter: dict, org_id_path: str, owner_label: str) -> None:
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

            self.revoke(access_key=account.access_key, org_id=account.owner_org_id)
            logger.info("Revoked temporary storage account for {}", owner_label)

            account.delete()
            logger.debug("Deleted temporary storage account record for {}", owner_label)
        except Exception as error:
            logger.warning(
                "Failed to revoke temporary storage credentials for {}: {}", owner_label, error
            )

    def revoke(self, access_key: str, org_id: int) -> None:
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
        asyncio.run(
            self._revoke_temporary_service_account(org_creds=org_creds, access_key=access_key)
        )

    async def _revoke_temporary_service_account(self, org_creds, access_key: str) -> None:
        gateway = StorageAdminGateway(
            host=settings.STORAGE_ENDPOINT,
            access_key=org_creds.access_key,
            secret_key=org_creds.secret_key,
        )
        try:
            await gateway.delete_service_account(access_key)
        finally:
            await gateway.close()


session_credential_service = SessionCredentialService()
