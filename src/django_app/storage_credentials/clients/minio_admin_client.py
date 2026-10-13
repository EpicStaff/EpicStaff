"""Thin async gateway over `miniopy_async.MinioAdmin`.

Policy attachment for a named (non-service-account) storage user is a two-step
operation on this server version/client: `policy_add` registers the policy
under a name, then `policy_set` attaches that name to the user. There is no
single-call "inline" policy attach for a regular IAM user in `miniopy_async`
(unlike `add_service_account`, which does accept an inline `policy_file`).
"""

import asyncio
import hashlib
import json
import secrets
import ssl
import string
import tempfile
from datetime import UTC, datetime, timedelta
from typing import Any

import certifi
from aiohttp import (
    ClientConnectorError,
    ClientResponse,
    ClientSession,
    ClientTimeout,
    ServerDisconnectedError,
    TCPConnector,
)
from aiohttp_retry import ExponentialRetry, RetryClient
from Crypto.Cipher import AES
from loguru import logger
from miniopy_async import MinioAdmin as _MinioAdminClient
from miniopy_async.credentials import StaticProvider
from miniopy_async.crypto import (
    _MAX_CHUNK_SIZE,
    _NONCE_LEN,
    _SALT_LEN,
    _TAG_LEN,
    _generate_key,
    _get_cipher,
    _mark_as_last,
    _update_nonce_id,
    encrypt,
)
from miniopy_async.error import MinioAdminException
from miniopy_async.minioadmin import _COMMAND

from storage_credentials.exceptions import (
    StorageCredentialConfigError,
    TemporaryCredentialIssueError,
    TemporaryCredentialListError,
    TemporaryCredentialRevokeError,
)

# PBKDF2 parameters for AEAD ID 2 ("pbkdf2AESGCM")
_PBKDF2_AEAD_ID = 2
_PBKDF2_ITERATIONS = 8192
_PBKDF2_KEY_LENGTH = 32
_HEADER_LENGTH = _SALT_LEN + 1 + _NONCE_LEN


class _AdminResponseDecryptor:
    """Decrypts a MinIO-admin-API-shaped response, including AEAD ID 2
    (PBKDF2 + AES-256-GCM), which miniopy_async's own `crypto.decrypt()`
    doesn't support. AEAD ID 0/1 (Argon2id-derived) are delegated to
    miniopy_async's own, already-tested key-derivation/cipher functions --
    only the missing ID 2 branch is new here. Mirrors the shape of
    `miniopy_async.crypto.DecryptReader`"""

    def __init__(self, header: bytes, secret: bytes):
        if len(header) != _HEADER_LENGTH:
            raise OSError("insufficient data")
        self._salt = header[:32]
        self._aead_id = header[32]
        self._nonce = header[33:]
        self._key = self._derive_key(secret, self._salt, self._aead_id)
        padded_nonce = self._nonce + b"\x00\x00\x00\x00"
        self._additional_data = self._generate_additional_data(
            self._aead_id, self._key, padded_nonce
        )
        self._count = 0

    @staticmethod
    def _derive_key(secret: bytes, salt: bytes, aead_id: int) -> bytes:
        if aead_id == _PBKDF2_AEAD_ID:
            return hashlib.pbkdf2_hmac(
                "sha256", secret, salt, _PBKDF2_ITERATIONS, dklen=_PBKDF2_KEY_LENGTH
            )
        return _generate_key(secret, salt)

    @classmethod
    def _cipher(cls, aead_id: int, key: bytes, nonce: bytes):
        if aead_id == _PBKDF2_AEAD_ID:
            return AES.new(key, AES.MODE_GCM, nonce)
        return _get_cipher(aead_id, key, nonce)

    @classmethod
    def _generate_additional_data(cls, aead_id: int, key: bytes, padded_nonce: bytes) -> bytes:
        """Same construction as miniopy_async.crypto._generate_additional_data,
        but routed through our own cipher dispatch (the library's version
        calls the library's _get_cipher, which raises on AEAD ID 2)."""
        cipher = cls._cipher(aead_id, key, padded_nonce)
        return b"\x00" + cipher.digest()

    def _decrypt_chunk(self, payload: bytes, last_chunk: bool) -> bytes:
        self._count += 1
        additional_data = self._additional_data
        if last_chunk:
            additional_data = _mark_as_last(additional_data)
        padded_nonce = _update_nonce_id(self._nonce, self._count)
        cipher = self._cipher(self._aead_id, self._key, padded_nonce)
        cipher.update(additional_data)
        hmac_tag = payload[-_TAG_LEN:]
        encrypted_data = payload[:-_TAG_LEN]
        return cipher.decrypt_and_verify(encrypted_data, hmac_tag)

    async def decrypt(self, response: ClientResponse) -> bytes:
        """Mirrors DecryptReader._read_chunk()/_read(): always buffer one
        byte more than a full chunk+tag before decrypting, so a short read
        on the next iteration (or EOF) tells us this chunk was the last one
        -- the wire format has no explicit chunk count."""
        result = b""
        chunk = b""
        is_closed = False
        while True:
            while not is_closed and len(chunk) != (1 + _MAX_CHUNK_SIZE):
                piece = await response.content.read(1 + _MAX_CHUNK_SIZE - len(chunk))
                chunk += piece
                if len(piece) == 0:
                    is_closed = True
            if len(chunk) == 0:
                break
            length = _MAX_CHUNK_SIZE
            last_chunk = is_closed
            if len(chunk) < length:
                length = len(chunk)
                last_chunk = True
            payload, chunk = chunk[:length], chunk[length:]
            result += self._decrypt_chunk(payload, last_chunk)
            if last_chunk:
                break
        return result


_ACCESS_KEY_LENGTH = 20
_SECRET_KEY_LENGTH = 40
_ACCESS_KEY_ALPHABET = string.ascii_uppercase + string.digits
_SECRET_KEY_ALPHABET = string.ascii_letters + string.digits


def _generate_credential(length: int, alphabet: str) -> str:
    """Generate secrets with specified length."""
    return "".join(secrets.choice(alphabet) for _ in range(length))


class StorageAdminGateway:
    def __init__(self, host: str, access_key: str, secret_key: str):
        secure, endpoint = self._split_host(host)
        session = self._create_session()
        self._client = _MinioAdminClient(
            endpoint=endpoint,
            credentials=StaticProvider(access_key, secret_key),
            secure=secure,
            session=session,
        )

    @staticmethod
    def _create_session() -> RetryClient:
        """Create an aiohttp ClientSession with custom shorter timeout values and retry logic.

        The default MinioAdmin timeout is 300s (5 minutes) for both connect and
        socket read. This reduces it to significantly shorter values to prevent
        long-lived transactions from holding database connections during storage
        service failures. Transactions using StorageAdminGateway will now timeout in
        seconds, not minutes.

        Timeout values:
        - connect: 10s (time to establish TCP connection)
        - sock_read: 15s (time waiting for first byte from server)

        Retry configuration:
        - Retries on HTTP 5xx statuses (500, 502, 503, 504)
        - Retries on network errors (connection errors, server disconnect, timeouts)
        - Exponential backoff with up to 5 retry attempts
        """
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        timeout = ClientTimeout(connect=10, sock_read=15)
        connector = TCPConnector(limit=10, ssl=ssl_context)
        session = ClientSession(connector=connector, timeout=timeout)

        retry_options = ExponentialRetry(
            attempts=5,
            statuses={500, 502, 503, 504},
            exceptions={
                ClientConnectorError,
                ServerDisconnectedError,
                asyncio.TimeoutError,
            },
        )
        return RetryClient(client_session=session, retry_options=retry_options)

    @staticmethod
    def _split_host(value: str) -> tuple[bool, str]:
        parts = value.split("://")
        if len(parts) != 2:
            logger.error(
                "STORAGE_ENDPOINT is empty or malformed: expected `scheme://host[:port]`, got {!r}",
                value,
            )
            raise StorageCredentialConfigError()
        http, endpoint = parts
        return http == "https", endpoint

    async def close(self) -> None:
        """`miniopy_async.MinioAdmin` lazily opens an aiohttp session on its
        first request and never exposes a public way to close it. Reaching
        into the private `_session` attribute is the only way to release
        those sockets -- there is no public API on this library for it.

        `RetryClient.close()` already closes the `ClientSession` it wraps
        (stored on its own private `_client` attribute) -- there is nothing
        further to close here."""
        session = getattr(self._client, "_session", None)
        if session is not None:
            await session.close()

    # --- org-level (long-lived) IAM user ---------------------------------

    async def add_user(self, access_key: str, secret_key: str) -> None:
        await self._client.user_add(access_key, secret_key)

    async def remove_user(self, access_key: str) -> None:
        """Removing the parent user cascades: the storage backend revokes all of that
        user's service accounts along with it.

        Idempotent against RustFS's own error-code quirk: removing a user that
        already doesn't exist returns 500 InternalError here, not 404.
        That specific case means deprovisioning already achieved its goal,
        so it's treated as success, not retried as a failure.
        """
        try:
            await self._client.user_remove(access_key)
        except MinioAdminException as error:
            if "does not exist" in error._body.lower():
                return
            raise

    async def create_named_policy(self, policy_name: str, policy: dict[str, Any]) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json") as policy_file:
            json.dump(policy, policy_file)
            policy_file.flush()
            await self._client.policy_add(policy_name, policy_file.name)

    async def attach_named_policy(self, policy_name: str, user: str) -> None:
        await self._client.policy_set(policy_name, user=user)

    async def remove_named_policy(self, policy_name: str) -> None:
        await self._client.policy_remove(policy_name)

    # --- per-execution (temporary) service account ------------------------

    async def create_service_account(
        self, policy: dict[str, Any], expiration: timedelta | None = None
    ) -> tuple[str, str]:
        """Mint a temporary service account scoped to `policy`. Returns
        (access_key, secret_key).

        Generates credentials on the client side to avoid decryption issues with
        miniopy_async (which fails to decrypt responses with AEAD ID 2). Success
        is determined by the absence of an exception from _url_open; the
        credentials are known immediately after generation since they were
        supplied in the request.

        Args:
            policy: IAM policy dict scoped to allowed paths.
            expiration: Lifetime of the account (timedelta). If None, no expiration is set.

        Returns:
            Tuple of (access_key, secret_key).
        """
        access_key = _generate_credential(_ACCESS_KEY_LENGTH, _ACCESS_KEY_ALPHABET)
        secret_key = _generate_credential(_SECRET_KEY_LENGTH, _SECRET_KEY_ALPHABET)

        try:
            data = {
                "status": "enabled",
                "accessKey": access_key,
                "secretKey": secret_key,
                "policy": policy,
            }
            if expiration is not None:
                expiration_str = (datetime.now(UTC) + expiration).strftime("%Y-%m-%dT%H:%M:%SZ")
                data["expiration"] = expiration_str

            body = json.dumps(data).encode()
            admin_creds = await self._client._provider.retrieve()
            encrypted_body = encrypt(body, admin_creds.secret_key)

            response = await self._client._url_open(
                "PUT",
                _COMMAND.SERVICE_ACCOUNT_ADD,
                body=encrypted_body,
            )
            # Explicitly drain and release the response to free the connection
            # back to the TCPConnector pool.
            await response.read()
            return access_key, secret_key
        except MinioAdminException as error:
            logger.exception("Failed to mint temporary service account: {}", error)
            raise TemporaryCredentialIssueError() from error
        except (TimeoutError, ClientConnectorError, ServerDisconnectedError) as error:
            logger.exception("Failed to mint temporary service account (network error): {}", error)
            raise TemporaryCredentialIssueError() from error

    async def delete_service_account(self, access_key: str) -> None:
        try:
            await self._client.delete_service_account(access_key)
        except Exception as error:
            logger.exception(
                "Failed to revoke service account '{}': {}",
                access_key,
                error,
            )
            raise TemporaryCredentialRevokeError() from error

    async def list_service_accounts(self, user: str) -> list[dict[str, Any]]:
        """Active service accounts of `user`, each carrying at least
        `accessKey` and `expiration` (ISO-8601, server-supplied).

        Bypasses `miniopy_async`'s own `list_service_account()`/`decrypt()`:
        that always fails on RustFS, which replies with AEAD ID 2 (see
        `_AdminResponseDecryptor`). `_url_open` still does the actual HTTP
        request/auth/retry -- only the response decryption is replaced."""
        response = None
        try:
            response = await self._client._url_open(
                "GET",
                _COMMAND.SERVICE_ACCOUNT_LIST,
                query_params={"user": user},
            )
            admin_creds = await self._client._provider.retrieve()
            decryptor = _AdminResponseDecryptor(
                await response.content.read(_HEADER_LENGTH), admin_creds.secret_key.encode()
            )
            raw = await decryptor.decrypt(response)
        except MinioAdminException as error:
            logger.exception(
                "Failed to list service accounts for user '{}': {}",
                user,
                error,
            )
            raise TemporaryCredentialListError() from error
        except (TimeoutError, ClientConnectorError, ServerDisconnectedError) as error:
            logger.exception(
                "Failed to list service accounts for user '{}' (network error): {}",
                user,
                error,
            )
            raise TemporaryCredentialListError() from error
        except (OSError, ValueError) as error:
            # _AdminResponseDecryptor raises OSError on a malformed/short
            # header and ValueError (via decrypt_and_verify) on a bad AEAD
            # id or failed tag check -- domain-wrap these too, and release
            # the response either way: unlike the happy path (which always
            # reads to EOF and lets aiohttp auto-release), a failure here
            # exits mid-stream and would otherwise leak the connection out
            # of the TCPConnector(limit=10) pool.
            logger.exception(
                "Failed to decrypt service account list for user '{}': {}",
                user,
                error,
            )
            raise TemporaryCredentialListError() from error
        finally:
            if response is not None:
                response.release()
        return json.loads(raw).get("accounts") or []
