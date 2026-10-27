"""The Ed25519 keys gateway contexts are signed with, and the JWKS plugins verify them by.

The newest key that is not retired signs. A rotation retires every other key at once; a
retired key stays in the JWKS for `RETIRED_KEY_RETENTION`, so a context signed just before
the rotation (it lives 60 s) and a plugin whose runtime file is a little behind still verify.
The first key is created at start-up (`seed_plugin_node`), never by a request, so reading
the keys never writes and two first uses cannot make two keys.
"""

import base64
import secrets
import time
from dataclasses import dataclass
from datetime import timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from epicstaff_plugin.contracts.gateway_context import Jwk, Jwks
from tables.services.secrets import secret_encryption

from plugins.audit import log_signing_key_rotation
from plugins.exceptions import SigningKeyMissingError
from plugins.models import PluginSigningKey

RETIRED_KEY_RETENTION = timedelta(hours=24)
# How long one process keeps using the signing key it loaded before it looks for a newer one,
# so the gateway check does not read and decrypt it on every request.
ACTIVE_KEY_CACHE_SECONDS = 10
# Serializes creating and rotating keys across processes ("plugsign" as a number).
_KEY_CHANGE_LOCK_ID = 0x706C7567_7369676E


@dataclass(frozen=True)
class ActiveSigningKey:
    kid: str
    private_key: Ed25519PrivateKey


class PluginSigningKeyService:
    """Creates, rotates and publishes the context-signing keys."""

    def ensure_key(self) -> PluginSigningKey:
        """Create the first signing key unless one that is not retired exists; return the active one.

        Run at start-up. Safe to run from several processes at once.
        """
        with transaction.atomic():
            _lock_key_changes()
            row = _newest_unretired()
            return row if row is not None else _create_key()

    def active_key(self) -> ActiveSigningKey:
        """Return the key new contexts are signed with.

        Raises:
            SigningKeyMissingError: No key exists yet.
        """
        row = _newest_unretired()
        if row is None:
            raise SigningKeyMissingError()
        return ActiveSigningKey(kid=row.kid, private_key=_private_key(row))

    def jwks(self) -> Jwks:
        """Return the active key and every key retired less than 24 h ago, newest first.

        Raises:
            SigningKeyMissingError: No key exists yet.
        """
        rows = list(_published_keys(timezone.now() - RETIRED_KEY_RETENTION))
        if not rows:
            raise SigningKeyMissingError()
        return Jwks(keys=[_jwk(row) for row in rows])

    def rotate(self) -> PluginSigningKey:
        """Make a new key the signing key and retire every key that was not retired yet."""
        with transaction.atomic():
            _lock_key_changes()
            retiring = list(
                PluginSigningKey.objects.select_for_update().filter(retired_at__isnull=True)
            )
            PluginSigningKey.objects.filter(pk__in=[row.pk for row in retiring]).update(
                retired_at=timezone.now()
            )
            created = _create_key()
        cached_signing_key.clear()
        log_signing_key_rotation(created.kid, [row.kid for row in retiring])
        return created


class _CachedSigningKey:
    """The active key of this process, reloaded at most every `ACTIVE_KEY_CACHE_SECONDS`."""

    def __init__(self):
        self._key: ActiveSigningKey | None = None
        self._loaded_at = 0.0

    def get(self) -> ActiveSigningKey:
        if self._key is None or time.monotonic() - self._loaded_at > ACTIVE_KEY_CACHE_SECONDS:
            self._key = PluginSigningKeyService().active_key()
            self._loaded_at = time.monotonic()
        return self._key

    def clear(self) -> None:
        self._key = None


cached_signing_key = _CachedSigningKey()


def _lock_key_changes() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_KEY_CHANGE_LOCK_ID])


def _newest_unretired() -> PluginSigningKey | None:
    return (
        PluginSigningKey.objects.filter(retired_at__isnull=True)
        .order_by("-created_at", "-pk")
        .first()
    )


def _published_keys(cutoff):
    return PluginSigningKey.objects.filter(
        Q(retired_at__isnull=True) | Q(retired_at__gt=cutoff)
    ).order_by("-created_at", "-pk")


def _create_key() -> PluginSigningKey:
    private_key = Ed25519PrivateKey.generate()
    kid = secrets.token_hex(8)
    seed = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    sealed = secret_encryption.encrypt(text=base64.b64encode(seed).decode("ascii"))
    return PluginSigningKey.objects.create(
        kid=kid,
        private_key_encrypted=sealed.encryptedtext,
        public_key=Jwk.from_public_key(kid, private_key.public_key()).x,
    )


def _private_key(row: PluginSigningKey) -> Ed25519PrivateKey:
    seed = base64.b64decode(secret_encryption.decrypt(encryptedtext=row.private_key_encrypted))
    return Ed25519PrivateKey.from_private_bytes(seed)


def _jwk(row: PluginSigningKey) -> Jwk:
    return Jwk(kty="OKP", crv="Ed25519", x=row.public_key, kid=row.kid, alg="EdDSA", use="sig")
