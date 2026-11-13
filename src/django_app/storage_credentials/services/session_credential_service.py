"""Issue, persist, and revoke temporary storage credentials.

Three callers share this module: a graph session (one account per storage grant and
flow, reused by the nodes that share them), a django "Test run" execution (one
per-execution account, no Session involved), and a realtime chat (one
account reused for the whole voice session). Each mints and persists
synchronously via `_mint_and_persist`, keyed to its own
`TemporaryStorageAccount` FK (`session`/`python_code_result`/
`realtime_agent_chat` -- exactly one set per row, see that model's
`CheckConstraint`). Revocation mirrors that split: one `revoke_for_*` entry
point per owner type, each resolving the owning organization through its own
FK path and then sharing `_revoke_and_delete`, which is the single place that
talks to the storage backend to delete a service account and drop its row.

Python code writes to storage without telling django, so each account records the
folders its policy grants, and a revocation that ends a run first reconciles them into
the file index (`_reconcile_granted_folders`).
"""

import asyncio
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.db.models import F
from django.db.models.functions import Coalesce
from django.utils import timezone
from loguru import logger
from rbac.models import Organization
from src.shared.models.sessions import SessionData
from src.shared.models.storage_scope import StorageAction, StorageCredentials
from tables.models import PythonCodeResult, RealtimeAgentChat, Session
from tables.services.storage_service import get_storage_backend
from tables.services.storage_service.reconciler import StorageReconciler

from storage_credentials.clients.minio_admin_client import StorageAdminGateway
from storage_credentials.exceptions import (
    CredentialScopeValidationError,
    TemporaryCredentialIssueError,
)
from storage_credentials.models import TemporaryStorageAccount
from storage_credentials.policies import build_temporary_policy
from storage_credentials.resource_names import org_storage_prefix
from storage_credentials.services.org_credential_store import org_credential_store
from storage_credentials.services.scope_validator import credential_scope_validator
from storage_credentials.services.storage_demand_collector import (
    collect_storage_demand,
    collect_storage_grant_demand,
)


@dataclass(frozen=True)
class SessionStorageCredentials:
    """The temporary storage accounts minted for one graph session.

    Attributes:
        default: The account for code with no storage grant of its own (an agent's python
            tool). None when no such code needs storage.
        by_grant: The account of each `storage_account_key` (grant and flow) used by a
            storage-using node or code slot. Several keys may share one account when they
            allow the same actions on the same files.
    """

    default: StorageCredentials | None = None
    by_grant: dict[str, StorageCredentials] = field(default_factory=dict)


@dataclass(frozen=True)
class _AccountRequest:
    """One account to mint: what it may do to the attached paths, and which paths those are."""

    shared_actions: frozenset[StorageAction]
    allowed_paths: frozenset[str]


@dataclass(frozen=True)
class _PlannedAccount:
    """One account about to be minted: its actions, every folder its policy grants, and the policy."""

    shared_actions: frozenset[StorageAction]
    granted_folders: frozenset[str]
    policy: dict


class SessionCredentialService:
    """Service for processing temporary storage credentials."""

    def issue_for_session(
        self, session_data: SessionData, session_orm: Session, org: Organization
    ) -> StorageCredentials | None:
        """Mint and persist the temporary storage account of a session, and return the default one.

        See `issue_session_accounts`, which also returns the accounts of the session's
        storage grants; this returns only `default`.
        """
        return self.issue_session_accounts(session_data, session_orm, org).default

    def issue_session_accounts(
        self, session_data: SessionData, session_orm: Session, org: Organization
    ) -> SessionStorageCredentials:
        """Mint and persist the temporary storage accounts a graph session needs.

        Traverses the session graph to determine if storage access is needed. If yes,
        mints one temporary service account per grant and flow: it allows exactly the
        grant's actions on the paths attached to that flow, so a sub-flow's grant never
        reaches its parent's files. Code with no grant (an agent's python tool) gets a
        default account allowing every action on the paths of that code. The session's
        own folder (`sessions/<id>/`) allows every action in all of them. Each account is
        persisted in TemporaryStorageAccount.

        Entries that end up with the same actions on the same paths share one account.
        The accounts are minted concurrently. Nothing here reads who started the run.

        Returns:
            The accounts; empty when no node needs storage.

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
            return SessionStorageCredentials()

        logger.info(
            "Session {} requires storage access. Paths: {}, node-declared org_prefix: {}",
            session_orm.id,
            union_allowed_paths,
            node_declared_org_prefix,
        )
        demand = collect_storage_grant_demand(session_data)
        keys_by_request: dict[_AccountRequest, list[str]] = defaultdict(list)
        default_request = _AccountRequest(frozenset(StorageAction), demand.ungranted_paths)
        if demand.has_ungranted:
            keys_by_request[default_request] = []
        for key, (grant, paths) in sorted(demand.accounts.items()):
            keys_by_request[_AccountRequest(grant.actions, paths)].append(key)
        requests = list(keys_by_request)
        credentials = self._mint_accounts(
            requests=requests,
            org_id=org.id,
            fk_field="session",
            fk_value=session_orm,
            owner_label=f"session {session_orm.id}",
            own_paths=[f"sessions/{session_orm.id}/"],
        )
        credentials_by_request = dict(zip(requests, credentials, strict=True))
        return SessionStorageCredentials(
            default=credentials_by_request[default_request] if demand.has_ungranted else None,
            by_grant={
                key: credentials_by_request[request]
                for request, keys in keys_by_request.items()
                for key in keys
            },
        )

    def issue_for_test_run(
        self,
        python_code_result: PythonCodeResult,
        storage_allowed_paths: list[str],
        org_id: int,
        *,
        own_paths: list[str],
        shared_actions: frozenset[StorageAction],
    ) -> StorageCredentials:
        """Mint and persist temporary storage credentials for a django "Test run"
        execution. Unlike `issue_for_session`, the caller has already determined
        `use_storage=True`, so this always mints (never returns None).

        `shared_actions` is what the code may do to `storage_allowed_paths` outside
        `own_paths`: the saved grant of a tested node, none for bare tool code.

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
            shared_actions=shared_actions,
        )

    def issue_for_realtime_chat(
        self,
        realtime_agent_chat: RealtimeAgentChat,
        storage_allowed_paths: list[str],
        org_id: int,
    ) -> StorageCredentials:
        """Mint and persist temporary storage credentials for a realtime chat
        session. One account for the whole chat, reused by every storage tool
        call within it (mirrors `issue_for_session`'s one-per-session reuse).

        Raises:
            CredentialScopeValidationError: If the given scope is missing,
            malformed, or escapes the org's own prefix.
            TemporaryCredentialIssueError: If minting or DB persistence fails.
        """
        return self._mint_and_persist(
            allowed_paths=storage_allowed_paths,
            org_id=org_id,
            fk_field="realtime_agent_chat",
            fk_value=realtime_agent_chat,
            owner_label=f"realtime chat {realtime_agent_chat.id}",
            own_paths=[],
            shared_actions=frozenset(StorageAction),
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
        shared_actions: frozenset[StorageAction],
    ) -> StorageCredentials:
        """Mint and persist the one account of a test run or a realtime chat; see `_mint_accounts`."""
        return self._mint_accounts(
            requests=[_AccountRequest(shared_actions, frozenset(allowed_paths))],
            org_id=org_id,
            fk_field=fk_field,
            fk_value=fk_value,
            owner_label=owner_label,
            own_paths=own_paths,
        )[0]

    def _mint_accounts(
        self,
        *,
        requests: list[_AccountRequest],
        org_id: int,
        fk_field: str,
        fk_value,
        owner_label: str,
        own_paths: list[str],
    ) -> list[StorageCredentials]:
        """Shared mint + persist body for all three `issue_for_*` entry points.

        Mints one account per entry of `requests` concurrently, and returns their
        credentials in the same order. Every account of a call belongs to the same owner
        and is persisted with its own actions and folders.

        Not best-effort: any failure here -- minting or persisting -- raises
        `TemporaryCredentialIssueError`, and the caller's own execution does not
        proceed. A service account that did mint before a DB-write failure is
        never rolled back; with a positive TTL it stops authenticating on its own
        regardless of the missing row, and with `STORAGE_TEMP_CREDENTIALS_TTL_HOURS
        <= 0` it is left to the revocation path and the manager's cleanup job. When one
        of several concurrent mints fails, the ones that succeeded are revoked at once.

        `allowed_paths` are namespaced under the prefix of the org named by
        `org_id` -- the org whose credentials do the minting -- never under a
        prefix declared by the graph data being executed. The two are expected to
        agree; deriving it here is what makes a tampered or stale node-level
        `storage_org_prefix` unable to reach another org's objects.

        `own_paths` are the run's own folders, computed by the caller and never read
        from node data; they always allow every action. The rest of a request's
        `allowed_paths` allow only its `shared_actions`. A request with none of them has
        the shared folders left out, and the run still gets its own folders.

        Raises:
            CredentialScopeValidationError: A request's `allowed_paths` is empty or escapes
                the org prefix, or nothing is left to grant because an account may
                do nothing to the shared folders and the run has no folder of its own.
            TemporaryPolicyTooLargeError: too many files are attached for one policy.
            TemporaryCredentialIssueError: minting or persisting failed.
        """
        planned: list[_PlannedAccount] = []
        for request in requests:
            shared_actions = request.shared_actions
            scoped_folders = credential_scope_validator.validate(
                org_id=org_id,
                storage_org_prefix=org_storage_prefix(org_id),
                storage_allowed_paths=sorted(request.allowed_paths),
                own_paths=own_paths,
            )
            shared_folders = scoped_folders.shared
            if not shared_actions:
                logger.info(
                    "Dropping {} shared storage folder(s) of an account of {}: it may do "
                    "nothing to them",
                    len(shared_folders),
                    owner_label,
                )
                shared_folders = frozenset()
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
            planned.append(
                _PlannedAccount(shared_actions, scoped_folders.own | shared_folders, policy)
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
            minted = asyncio.run(
                self._mint_temporary_service_accounts(
                    org_creds=org_creds,
                    policies=[account.policy for account in planned],
                    expiration=expiration,
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

        credentials: list[StorageCredentials] = []
        persisted_keys: set[str] = set()
        try:
            issued_at = timezone.now()
            rows: list[TemporaryStorageAccount] = []
            for account, (access_key, secret_key) in zip(planned, minted, strict=True):
                shared_action_list = [
                    action for action in StorageAction if action in account.shared_actions
                ]
                rows.append(
                    TemporaryStorageAccount(
                        access_key=access_key,
                        issued_at=issued_at,
                        shared_actions=[action.value for action in shared_action_list],
                        granted_folders=self._org_relative_grants(org_id, account.granted_folders),
                        **{fk_field: fk_value},
                    )
                )
                credentials.append(
                    StorageCredentials(
                        access_key=access_key,
                        secret_key=secret_key,
                        shared_actions=shared_action_list,
                        own_paths=sorted(own_paths),
                    )
                )
            # One INSERT: it either persists every row or none, so a failure leaves every
            # minted account for `_revoke_unpersisted`.
            TemporaryStorageAccount.objects.bulk_create(rows)
            persisted_keys.update(row.access_key for row in rows)
            logger.info(
                "Persisted {} temporary storage account(s) for {}", len(credentials), owner_label
            )
        except Exception as error:
            logger.exception(
                "Failed to persist temporary storage account for {}: {}",
                owner_label,
                error,
            )
            self._revoke_unpersisted(org_id, org_creds, minted, persisted_keys)
            raise TemporaryCredentialIssueError() from error

        return credentials

    def _revoke_unpersisted(self, org_id, org_creds, minted, persisted_keys: set[str]) -> None:
        """Revoke the minted accounts that have no row, which nothing else would ever revoke.

        Best-effort: a failure is logged, and with a TTL the account expires on its own.
        """
        orphaned = [access_key for access_key, _ in minted if access_key not in persisted_keys]
        if not orphaned:
            return
        try:
            asyncio.run(self._delete_service_accounts(org_creds=org_creds, access_keys=orphaned))
        except Exception as error:
            logger.warning(
                "Failed to revoke {} unrecorded temporary storage account(s) in org {}: {}",
                len(orphaned),
                org_id,
                error,
            )

    @staticmethod
    def _org_relative_grants(org_id: int, scoped_folders: Iterable[str]) -> list[str]:
        """The granted paths without the org prefix, sorted, in the form the file index uses."""
        org_prefix = f"{org_storage_prefix(org_id)}/"
        return sorted(folder.removeprefix(org_prefix) for folder in scoped_folders)

    async def _mint_temporary_service_accounts(
        self, org_creds, policies: list[dict], expiration: timedelta | None
    ) -> list[tuple[str, str]]:
        """Mint one account per policy concurrently; returns (access key, secret key) in order.

        If any mint fails, the accounts of the others are revoked before the first failure
        is raised, so a failed session start leaves none behind.
        """
        results = await asyncio.gather(
            *(
                self._mint_temporary_service_account(
                    org_creds=org_creds, policy=policy, expiration=expiration
                )
                for policy in policies
            ),
            return_exceptions=True,
        )
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            minted_keys = [result[0] for result in results if not isinstance(result, BaseException)]
            if minted_keys:
                await self._delete_service_accounts(org_creds=org_creds, access_keys=minted_keys)
            raise failures[0]
        return list(results)

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

        Revokes every account of the owner: a graph session has several when its nodes
        carry different storage grants or live in flows with different files. The accounts
        of one organization are revoked together, with one credential lookup and one
        gateway. Deletes the `TemporaryStorageAccount` rows, in one query, only for the
        accounts the backend confirms are gone, so a failed revocation leaves that row for
        the manager's cleanup job to retry; the others are still revoked.

        `org_id_path` is an ORM lookup from `TemporaryStorageAccount` to the owning
        organization. It is resolved in the same query as the row via `F()`, so a
        broken ownership chain yields `None` instead of raising on attribute
        access.

        Every failure is swallowed and logged: all three callers run on a
        completion path where the owner's own work is already done, and
        `StorageAdminGateway` already classifies backend errors.
        """
        try:
            accounts = list(
                TemporaryStorageAccount.objects.filter(**owner_filter)
                .annotate(owner_org_id=F(org_id_path))
                .order_by("pk")
            )
        except Exception as error:
            logger.warning(
                "Failed to look up temporary storage accounts of {}: {}", owner_label, error
            )
            return
        if not accounts:
            logger.debug("No temporary storage account found for {}", owner_label)
            return

        accounts_by_org: dict[int, list[TemporaryStorageAccount]] = {}
        for account in accounts:
            if account.owner_org_id is None:
                logger.error(
                    "Cannot revoke temporary storage account for {}: no owning organization "
                    "reachable via {}. Leaving the row for cleanup.",
                    owner_label,
                    org_id_path,
                )
                continue
            accounts_by_org.setdefault(account.owner_org_id, []).append(account)

        # What the run wrote is synced into the file index once, over every folder any of
        # its accounts could write to: the accounts differ in the shared folders they got.
        granted_folders = self._union_of_granted_folders(accounts)
        synced = False
        for org_id, org_accounts in accounts_by_org.items():
            try:
                if not synced:
                    self._sync_run_storage(org_accounts[0], org_id, owner_label, granted_folders)
                    synced = True
                org_creds = org_credential_store.get(org_id=org_id)
                revoked_keys = set(
                    asyncio.run(
                        self._delete_service_accounts(
                            org_creds=org_creds,
                            access_keys=[account.access_key for account in org_accounts],
                        )
                    )
                )
                logger.info(
                    "Revoked {} temporary storage account(s) for {}", len(revoked_keys), owner_label
                )
                confirmed_pks = [
                    account.pk for account in org_accounts if account.access_key in revoked_keys
                ]
                TemporaryStorageAccount.objects.filter(pk__in=confirmed_pks).delete()
                logger.debug(
                    "Deleted {} temporary storage account record(s) for {}",
                    len(confirmed_pks),
                    owner_label,
                )
            except Exception as error:
                logger.warning(
                    "Failed to revoke temporary storage credentials for {}: {}", owner_label, error
                )

    @staticmethod
    def _reconcile_granted_folders(
        *, org_id: int, granted_folders: list[str] | None, owner_label: str
    ) -> None:
        """Index what a run that is ending wrote under its granted folders, before its account goes.

        Python code can write without reporting it, and a report is only a hint, so the
        storage itself is read: the file index and the org's used bytes then include what
        the run left behind. Best-effort: a failure is logged and never blocks the
        revocation. Executables stay unindexed, as the reconciler already does.

        Only adds and updates rows, never deletes them: other uploads and runs write to
        storage while this listing is taken, and sweeping would drop the rows of live
        files. The cost is that a row of an object the code deleted without reporting it
        stays and overcounts the org's bytes, until the manual reconcile fixes it.
        """
        # A granted folder holds every path granted under it, so reconciling those twice
        # would only list the same objects again.
        outermost: list[str] = []
        for path in sorted(granted_folders or []):
            if not any(kept.endswith("/") and path.startswith(kept) for kept in outermost):
                outermost.append(path)
        if not outermost:
            return
        try:
            reconciler = StorageReconciler(get_storage_backend(organization_prefix=""))
        except Exception as error:
            logger.warning("Cannot reconcile the end of {}: {}", owner_label, error)
            return
        for path in outermost:
            try:
                # A granted path ending in "/" is a folder, anything else a single file.
                if path.endswith("/"):
                    reconciler.reconcile_tree(org_id, prefix=path, sweep_stale_rows=False)
                else:
                    reconciler.reconcile_file(org_id, path, sweep_stale_rows=False)
            except Exception as error:
                logger.warning(
                    "Failed to reconcile '{}' of org {} into the file index at the end of {}: {}",
                    path,
                    org_id,
                    owner_label,
                    error,
                )

    @staticmethod
    def _union_of_granted_folders(accounts: Iterable[TemporaryStorageAccount]) -> list[str] | None:
        """The folders any of `accounts` was granted; None if none of them recorded its folders."""
        recorded = [
            account.granted_folders for account in accounts if account.granted_folders is not None
        ]
        if not recorded:
            return None
        return sorted({folder for folders in recorded for folder in folders})

    def _sync_run_storage(
        self,
        account: TemporaryStorageAccount,
        org_id: int,
        owner_label: str,
        granted_folders: list[str] | None = None,
    ) -> None:
        """Before an account is revoked: index what its run wrote.

        The reconcile only adds (see `_reconcile_granted_folders`). Best-effort, like the revocation.

        Args:
            granted_folders: The folders to reconcile, for a run with several accounts; the
                account's own when omitted.
        """
        self._reconcile_granted_folders(
            org_id=org_id,
            granted_folders=granted_folders
            if granted_folders is not None
            else account.granted_folders,
            owner_label=owner_label,
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
