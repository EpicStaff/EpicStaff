"""Service-account keys: what they look like, and how a new set is minted for a plugin.

Keys have a purpose (`ServiceAccountKeyPurpose`). Node keys are minted for the plugin node at
every runtime-credentials call; development keys only when a SuperAdmin downloads the
development runtime file. Each kind of minting touches only its own purpose, so neither
supersedes nor revokes the other's keys.

Lock order: the plugin's service accounts, in organization order, then their keys. Suspend
and resume lock one account, then its keys.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from plugins.audit import log_service_account_keys_minted
from plugins.models import (
    Plugin,
    PluginServiceAccount,
    PluginServiceAccountKey,
    ServiceAccountKeyPurpose,
)

KEY_PREFIX = "esp-"
# Characters of the key kept in clear as its public identifier.
PREFIX_LENGTH = 12
# How long the key a mint replaced keeps working, so a plugin process still holding it (the
# node rewrites the runtime file, the process reads it per request) is never cut off.
SUPERSEDED_KEY_LIFETIME = timedelta(minutes=10)


def hash_service_account_key(raw_key: str) -> str:
    """The sha256 of a key, as `PluginServiceAccountKey.key_hash` stores it."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MintedKey:
    """A key minted for one service account; `raw_key` exists only in this object."""

    service_account: PluginServiceAccount
    raw_key: str


class ServiceAccountKeyService:
    """Mints the keys a plugin's backend calls EpicStaff with, one per organization."""

    def mint_for_plugin(self, plugin: Plugin) -> list[MintedKey]:
        """Give every key-holding service account of `plugin` a new current node key.

        For each account, the previous current node key keeps working for ten more minutes
        and every node key superseded before it is revoked now, so at most two node keys of an
        account are ever valid. Development keys are left as they are. Runs in one transaction
        with four queries, however many organizations the plugin is granted to: the call
        either mints every key or none. Called inside a caller's transaction it is a
        savepoint, and the caller's rollback undoes it too; the `keys_minted` log line is
        written only once the mint is committed. Each account comes with its grant and
        organization.
        """
        with transaction.atomic():
            accounts = list(
                PluginServiceAccount.objects.key_holding()
                .filter(grant__plugin=plugin)
                .select_related("grant__org")
                .select_for_update(of=("self",))
                .order_by("grant__org_id")
            )
            if not accounts:
                return []
            # Read once the accounts are locked: a mint that waited for another one still
            # gives the key it supersedes its full ten minutes.
            now = timezone.now()
            account_ids = [account.pk for account in accounts]
            keys = PluginServiceAccountKey.objects.filter(
                service_account_id__in=account_ids,
                purpose=ServiceAccountKeyPurpose.NODE,
                revoked_at__isnull=True,
            )
            keys.filter(expires_at__isnull=False).update(revoked_at=now)
            keys.filter(expires_at__isnull=True).update(expires_at=now + SUPERSEDED_KEY_LIFETIME)
            minted = _create_keys(accounts, ServiceAccountKeyPurpose.NODE)
            org_ids = [account.grant.org_id for account in accounts]
            # Once the outermost transaction commits: a caller that rolls the mint back
            # (a runtime file that cannot be built) must leave no line saying keys exist.
            transaction.on_commit(
                lambda: log_service_account_keys_minted(plugin.identifier, org_ids)
            )
        return minted

    def mint_development_keys(self, plugin: Plugin) -> list[MintedKey]:
        """Replace every development key of `plugin` with one new key per key-holding account.

        Every development key of the plugin's accounts stops at once, with no overlap: a new
        download replaces the previous file. Node keys are left as they are. Four queries,
        however many organizations the plugin is granted to; inside a caller's transaction
        it is a savepoint. Each account comes with its grant and organization.
        """
        with transaction.atomic():
            account_ids = _lock_accounts(plugin)
            _revoke_development_keys(account_ids, timezone.now())
            holding = list(
                PluginServiceAccount.objects.key_holding()
                .filter(pk__in=account_ids)
                .select_related("grant__org")
                .order_by("grant__org_id")
            )
            return _create_keys(holding, ServiceAccountKeyPurpose.DEVELOPMENT)

    def revoke_development_keys(self, plugin: Plugin) -> int:
        """Revoke every development key of `plugin` that still works; return how many.

        Two queries: the accounts are locked first, as every mint locks them.
        """
        with transaction.atomic():
            return _revoke_development_keys(_lock_accounts(plugin), timezone.now())


def development_keys_issued_at(plugin: Plugin) -> datetime | None:
    """When the plugin's development keys that are not revoked were issued; None when none is."""
    return PluginServiceAccountKey.objects.filter(
        service_account__grant__plugin=plugin,
        purpose=ServiceAccountKeyPurpose.DEVELOPMENT,
        revoked_at__isnull=True,
    ).aggregate(issued_at=Max("created_at"))["issued_at"]


def _lock_accounts(plugin: Plugin) -> list[int]:
    """Lock every service account of the plugin, in the order the mints lock them."""
    return list(
        PluginServiceAccount.objects.select_for_update()
        .filter(grant__plugin=plugin)
        .order_by("grant__org_id")
        .values_list("pk", flat=True)
    )


def _revoke_development_keys(account_ids: list[int], now: datetime) -> int:
    if not account_ids:
        return 0
    return PluginServiceAccountKey.objects.filter(
        service_account_id__in=account_ids,
        purpose=ServiceAccountKeyPurpose.DEVELOPMENT,
        revoked_at__isnull=True,
    ).update(revoked_at=now)


def _create_keys(accounts: list[PluginServiceAccount], purpose: str) -> list[MintedKey]:
    minted = [MintedKey(service_account=account, raw_key=_new_raw_key()) for account in accounts]
    if minted:
        PluginServiceAccountKey.objects.bulk_create(
            PluginServiceAccountKey(
                service_account=key.service_account,
                purpose=purpose,
                prefix=key.raw_key[:PREFIX_LENGTH],
                key_hash=hash_service_account_key(key.raw_key),
            )
            for key in minted
        )
    return minted


def _new_raw_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)
