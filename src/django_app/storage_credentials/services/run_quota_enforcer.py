"""Keep an org within its storage quota after python code wrote past it.

Python code writes straight to storage with its run's temporary credentials, so a write
cannot be refused here: django hears of it afterwards. The only levers are the org's
storage bin, which a run acting as a user with FILES:DELETE may purge, and the run's own
credentials, which are revoked. A user's objects are never deleted.
"""

from django.db.models import Q
from loguru import logger
from tables.services.storage_service.quota import is_over_quota

from storage_credentials.models import TemporaryStorageAccount
from storage_credentials.services.run_bin_purge import purge_bin_for_run
from storage_credentials.services.session_credential_service import session_credential_service


class RunQuotaEnforcer:
    """Brings the org back under its quota after a run's write, or cuts the run off."""

    def enforce_after_write(
        self,
        *,
        org_id: int,
        access_key: str | None,
        session_id: int | None,
        execution_id: str,
    ) -> None:
        """Purge the org's oldest storage bin entries, or revoke the run's account, if over quota.

        Call after a write of the run was recorded at its stored size. The identifiers
        must come from the trusted execution record, never from what the code reported:
        they alone pick the account affected, and only one of org `org_id`. The access key
        names the account for every kind of run; `session_id` and `execution_id` serve
        events that carry none. A run whose account is already gone (a test run's is
        revoked before its mutations arrive) is left alone, as is any run when the org is
        within quota.

        The run's account is revoked when it may not purge the bin, or purging it all
        would not be enough.
        """
        if not is_over_quota(org_id):
            return
        run_label = f"execution {execution_id} (session {session_id})"
        logger.warning("Org {} is over its storage quota after writes of {}", org_id, run_label)
        account = self._account_of_run(org_id, access_key, session_id, execution_id)
        if account is None:
            logger.info("No temporary storage account left for {}; nothing to do", run_label)
            return

        purge_bin_for_run(account, org_id, run_label)
        if not is_over_quota(org_id):
            return

        logger.warning(
            "Revoking the temporary storage account of {}: org {} is still over its quota",
            run_label,
            org_id,
        )
        session_credential_service.revoke_access_keys([account.access_key])

    @staticmethod
    def _account_of_run(
        org_id: int, access_key: str | None, session_id: int | None, execution_id: str
    ) -> TemporaryStorageAccount | None:
        """The account the ids name, only if its run belongs to org `org_id`."""
        if access_key is not None:
            accounts = TemporaryStorageAccount.objects.filter(
                Q(session__graph__org_id=org_id)
                | Q(python_code_result__org_id=org_id)
                | Q(realtime_agent_chat__rt_agent_definition__agent_definition__org_id=org_id),
                access_key=access_key,
            )
        elif session_id is not None:
            accounts = TemporaryStorageAccount.objects.filter(
                session_id=session_id, session__graph__org_id=org_id
            )
        else:
            accounts = TemporaryStorageAccount.objects.filter(
                python_code_result__execution_id=execution_id,
                python_code_result__org_id=org_id,
            )
        return accounts.select_related("issued_for_user", "issued_for_root_user").first()


run_quota_enforcer = RunQuotaEnforcer()
