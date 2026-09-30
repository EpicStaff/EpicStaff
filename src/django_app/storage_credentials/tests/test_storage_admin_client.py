"""Tests for StorageAdminGateway.create_service_account() implementation.

Tests verify that temporary service account creation:
- Generates valid credentials on the client side
- Does NOT call decrypt() or add_service_account()
- Uses direct _url_open() with encrypted payload
- Returns generated keys without decryption
- Handles MinioAdminException correctly
"""

import asyncio
import json
import secrets
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientConnectorError, ServerDisconnectedError
from aiohttp.client_reqrep import ConnectionKey
from miniopy_async.error import MinioAdminException
from miniopy_async.minioadmin import _COMMAND

from storage_credentials.clients.minio_admin_client import StorageAdminGateway
from storage_credentials.exceptions import TemporaryCredentialIssueError


class TestCreateServiceAccount:
    """Tests for StorageAdminGateway.create_service_account()"""

    @pytest.fixture
    def gateway(self):
        """Create a StorageAdminGateway instance with mocked client."""
        with patch("storage_credentials.clients.minio_admin_client._MinioAdminClient"), \
             patch("storage_credentials.clients.minio_admin_client.StorageAdminGateway._create_session"):
            gateway = StorageAdminGateway(
                host="https://minio.example.com",
                access_key="admin_access_key",
                secret_key="admin_secret_key",
            )
            gateway._client = MagicMock()
            return gateway

    @staticmethod
    def _create_mock_response():
        """Helper to create a mock response object with a read() method
        returning binary data (the real response body is AEAD-encrypted,
        never valid UTF-8 text)."""
        mock_response = AsyncMock()
        mock_response.read = AsyncMock(return_value=b"")
        return mock_response

    @pytest.mark.asyncio
    async def test_returns_generated_keys_when_url_open_succeeds(self, gateway):
        """Verify that create_service_account returns generated keys without decryption."""
        policy = {"Version": "2012-10-17", "Statement": []}
        expiration = timedelta(hours=1)

        gateway._client._url_open = AsyncMock(return_value=self._create_mock_response())
        gateway._client._provider = MagicMock()
        gateway._client._provider.retrieve = AsyncMock()
        gateway._client._provider.retrieve.return_value = MagicMock(secret_key="admin_secret_key")

        access_key, secret_key = await gateway.create_service_account(policy, expiration)

        assert isinstance(access_key, str)
        assert isinstance(secret_key, str)
        assert len(access_key) == 20
        assert len(secret_key) == 40

    @pytest.mark.asyncio
    async def test_url_open_called_with_correct_payload(self, gateway):
        """Verify _url_open is called with encrypted body, not decrypt()."""
        policy = {"Version": "2012-10-17", "Statement": []}
        expiration = timedelta(hours=1)

        gateway._client._url_open = AsyncMock(return_value=self._create_mock_response())
        gateway._client._provider = MagicMock()
        gateway._client._provider.retrieve = AsyncMock()
        gateway._client._provider.retrieve.return_value = MagicMock(secret_key="admin_secret_key")

        await gateway.create_service_account(policy, expiration)

        gateway._client._url_open.assert_called_once()
        call_args = gateway._client._url_open.call_args
        assert call_args[0][0] == "PUT"
        assert call_args[0][1] == _COMMAND.SERVICE_ACCOUNT_ADD
        assert "body" in call_args[1]

    @pytest.mark.asyncio
    async def test_payload_contains_required_fields(self, gateway):
        """Verify the encrypted payload contains all required fields."""
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": "s3:GetObject",
                    "Resource": "arn:aws:s3:::bucket/prefix/*",
                }
            ],
        }
        expiration = timedelta(hours=2)

        with patch("storage_credentials.clients.minio_admin_client.encrypt") as mock_encrypt:
            mock_encrypt.return_value = b"encrypted_body"
            gateway._client._url_open = AsyncMock(return_value=self._create_mock_response())
            gateway._client._provider = MagicMock()
            gateway._client._provider.retrieve = AsyncMock()
            gateway._client._provider.retrieve.return_value = MagicMock(secret_key="admin_secret_key")

            await gateway.create_service_account(policy, expiration)

            encrypt_call = mock_encrypt.call_args
            encrypted_data = encrypt_call[0][0]
            payload = json.loads(encrypted_data.decode())

            assert payload["status"] == "enabled"
            assert "accessKey" in payload
            assert "secretKey" in payload
            assert payload["policy"] == policy
            assert "expiration" in payload

    @pytest.mark.asyncio
    async def test_expiration_format_is_iso8601(self, gateway):
        """Verify expiration timestamp is correctly formatted in ISO-8601."""
        policy = {"Version": "2012-10-17", "Statement": []}
        expiration = timedelta(hours=1)

        with patch("storage_credentials.clients.minio_admin_client.encrypt") as mock_encrypt:
            mock_encrypt.return_value = b"encrypted_body"
            gateway._client._url_open = AsyncMock(return_value=self._create_mock_response())
            gateway._client._provider = MagicMock()
            gateway._client._provider.retrieve = AsyncMock()
            gateway._client._provider.retrieve.return_value = MagicMock(secret_key="admin_secret_key")

            await gateway.create_service_account(policy, expiration)

            encrypt_call = mock_encrypt.call_args
            encrypted_data = encrypt_call[0][0]
            payload = json.loads(encrypted_data.decode())
            expiration_str = payload["expiration"]

            assert expiration_str.endswith("Z")
            datetime.strptime(expiration_str, "%Y-%m-%dT%H:%M:%SZ")

    @pytest.mark.asyncio
    async def test_credentials_generated_before_url_open(self, gateway):
        """Verify credentials are generated on client side before _url_open is called."""
        policy = {"Version": "2012-10-17", "Statement": []}
        expiration = timedelta(hours=1)
        generated_access_key = None
        generated_secret_key = None

        async def capture_url_open(*args, **kwargs):
            # Capture the payload to verify credentials were generated
            body = kwargs.get("body", b"")
            # We can't decrypt the body in this test, but we can verify it exists
            assert body, "Body should be encrypted"
            return self._create_mock_response()

        gateway._client._url_open = AsyncMock(side_effect=capture_url_open)
        gateway._client._provider = MagicMock()
        gateway._client._provider.retrieve = AsyncMock()
        gateway._client._provider.retrieve.return_value = MagicMock(secret_key="admin_secret_key")

        access_key, secret_key = await gateway.create_service_account(policy, expiration)

        assert access_key
        assert secret_key

    @pytest.mark.asyncio
    async def test_decrypt_not_called_on_success(self, gateway):
        """Verify decrypt() is NOT called on create_service_account."""
        policy = {"Version": "2012-10-17", "Statement": []}
        expiration = timedelta(hours=1)

        gateway._client._url_open = AsyncMock(return_value=self._create_mock_response())
        gateway._client._provider = MagicMock()
        gateway._client._provider.retrieve = AsyncMock()
        gateway._client._provider.retrieve.return_value = MagicMock(secret_key="admin_secret_key")

        with patch.object(gateway._client, "decrypt", wraps=gateway._client.decrypt) as mock_decrypt:
            await gateway.create_service_account(policy, expiration)
            mock_decrypt.assert_not_called()

    @pytest.mark.asyncio
    async def test_miniaoadmin_exception_raises_credential_issue_error(self, gateway):
        """Verify MinioAdminException is converted to TemporaryCredentialIssueError."""
        policy = {"Version": "2012-10-17", "Statement": []}
        expiration = timedelta(hours=1)

        error = MinioAdminException(code="400", body="Service account creation failed")
        gateway._client._url_open = AsyncMock(side_effect=error)
        gateway._client._provider = MagicMock()
        gateway._client._provider.retrieve = AsyncMock()
        gateway._client._provider.retrieve.return_value = MagicMock(secret_key="admin_secret_key")

        with pytest.raises(TemporaryCredentialIssueError) as exc_info:
            await gateway.create_service_account(policy, expiration)

        assert "Failed to mint temporary service account" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_generated_keys_meet_exact_length_requirements(self, gateway):
        """The storage backend rejects keys of any other length (empirically
        verified against a live RustFS container: a 43-char secret_key was
        rejected with `invalid secret key length`, only exactly 40 chars
        works) -- length must be exact, not just a minimum."""
        policy = {"Version": "2012-10-17", "Statement": []}
        expiration = timedelta(hours=1)

        gateway._client._url_open = AsyncMock(return_value=self._create_mock_response())
        gateway._client._provider = MagicMock()
        gateway._client._provider.retrieve = AsyncMock()
        gateway._client._provider.retrieve.return_value = MagicMock(secret_key="admin_secret_key")

        access_key, secret_key = await gateway.create_service_account(policy, expiration)

        assert len(access_key) == 20, "access_key must be exactly 20 chars"
        assert len(secret_key) == 40, "secret_key must be exactly 40 chars"
        assert access_key.isascii(), "access_key should be ASCII"
        assert secret_key.isascii(), "secret_key should be ASCII"

    @pytest.mark.asyncio
    async def test_multiple_calls_generate_different_credentials(self, gateway):
        """Verify each call generates different credentials (not reused)."""
        policy = {"Version": "2012-10-17", "Statement": []}
        expiration = timedelta(hours=1)

        gateway._client._url_open = AsyncMock(return_value=self._create_mock_response())
        gateway._client._provider = MagicMock()
        gateway._client._provider.retrieve = AsyncMock()
        gateway._client._provider.retrieve.return_value = MagicMock(secret_key="admin_secret_key")

        keys1 = await gateway.create_service_account(policy, expiration)
        keys2 = await gateway.create_service_account(policy, expiration)

        assert keys1 != keys2, "Each call should generate unique credentials"

    @pytest.mark.asyncio
    async def test_encryption_uses_admin_secret_key(self, gateway):
        """Verify encryption uses the admin's secret key from provider."""
        policy = {"Version": "2012-10-17", "Statement": []}
        expiration = timedelta(hours=1)
        expected_secret = b"admin_secret_key_bytes"

        with patch("storage_credentials.clients.minio_admin_client.encrypt") as mock_encrypt:
            mock_encrypt.return_value = b"encrypted_body"
            gateway._client._url_open = AsyncMock(return_value=self._create_mock_response())
            gateway._client._provider = MagicMock()
            gateway._client._provider.retrieve = AsyncMock()
            gateway._client._provider.retrieve.return_value = MagicMock(
                secret_key=expected_secret
            )

            await gateway.create_service_account(policy, expiration)

            encrypt_call = mock_encrypt.call_args
            assert encrypt_call[0][1] == expected_secret

    @pytest.mark.asyncio
    async def test_raises_on_minio_exception_variants(self, gateway):
        """Verify MinioAdminException variants are caught and converted."""
        policy = {"Version": "2012-10-17", "Statement": []}
        expiration = timedelta(hours=1)

        error = MinioAdminException(code="500", body="Internal server error")
        gateway._client._url_open = AsyncMock(side_effect=error)
        gateway._client._provider = MagicMock()
        gateway._client._provider.retrieve = AsyncMock()
        gateway._client._provider.retrieve.return_value = MagicMock(secret_key="admin_secret_key")

        with pytest.raises(TemporaryCredentialIssueError):
            await gateway.create_service_account(policy, expiration)

    @pytest.mark.asyncio
    async def test_response_read_called_to_free_connection(self, gateway):
        """Verify response.read() (not .text()) drains and frees the connection
        back to the pool. The body is AEAD-encrypted binary, not UTF-8 text --
        .text() crashes with UnicodeDecodeError on a real, non-empty response."""
        policy = {"Version": "2012-10-17", "Statement": []}
        expiration = timedelta(hours=1)

        mock_response = AsyncMock()
        mock_response.read = AsyncMock(return_value=b"\xc6\x00\x01binary-not-utf8")
        gateway._client._url_open = AsyncMock(return_value=mock_response)
        gateway._client._provider = MagicMock()
        gateway._client._provider.retrieve = AsyncMock()
        gateway._client._provider.retrieve.return_value = MagicMock(secret_key="admin_secret_key")

        await gateway.create_service_account(policy, expiration)

        mock_response.read.assert_called_once()

    @pytest.mark.asyncio
    async def test_client_connector_error_raises_credential_issue_error(self, gateway):
        """Verify ClientConnectorError is caught and converted to TemporaryCredentialIssueError."""
        policy = {"Version": "2012-10-17", "Statement": []}
        expiration = timedelta(hours=1)

        # A real ClientConnectorError always carries a real ConnectionKey --
        # aiohttp's own __str__ dereferences `connection_key.host`, so a
        # `None` key (as this test previously passed) crashes str(error)
        # with AttributeError instead of exercising the code under test.
        connection_key = ConnectionKey(
            host="storage",
            port=9000,
            is_ssl=False,
            ssl=False,
            proxy=None,
            proxy_auth=None,
            proxy_headers_hash=None,
        )
        error = None
        try:
            raise ClientConnectorError(connection_key, OSError("Connection refused"))
        except ClientConnectorError as e:
            error = e

        async def raise_connector_error(*args, **kwargs):
            raise error

        gateway._client._url_open = AsyncMock(side_effect=raise_connector_error)
        gateway._client._provider = MagicMock()
        gateway._client._provider.retrieve = AsyncMock()
        gateway._client._provider.retrieve.return_value = MagicMock(secret_key="admin_secret_key")

        with pytest.raises(TemporaryCredentialIssueError) as exc_info:
            await gateway.create_service_account(policy, expiration)

        assert "network error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_server_disconnected_error_raises_credential_issue_error(self, gateway):
        """Verify ServerDisconnectedError is caught and converted to TemporaryCredentialIssueError."""
        policy = {"Version": "2012-10-17", "Statement": []}
        expiration = timedelta(hours=1)

        # Create a real ServerDisconnectedError instance
        error = None
        try:
            raise ServerDisconnectedError()
        except ServerDisconnectedError as e:
            error = e

        async def raise_server_disconnected(*args, **kwargs):
            raise error

        gateway._client._url_open = AsyncMock(side_effect=raise_server_disconnected)
        gateway._client._provider = MagicMock()
        gateway._client._provider.retrieve = AsyncMock()
        gateway._client._provider.retrieve.return_value = MagicMock(secret_key="admin_secret_key")

        with pytest.raises(TemporaryCredentialIssueError) as exc_info:
            await gateway.create_service_account(policy, expiration)

        assert "network error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_asyncio_timeout_error_raises_credential_issue_error(self, gateway):
        """Verify asyncio.TimeoutError is caught and converted to TemporaryCredentialIssueError."""
        policy = {"Version": "2012-10-17", "Statement": []}
        expiration = timedelta(hours=1)

        async def raise_timeout(*args, **kwargs):
            raise asyncio.TimeoutError("Request timed out after 5 retries")

        gateway._client._url_open = AsyncMock(side_effect=raise_timeout)
        gateway._client._provider = MagicMock()
        gateway._client._provider.retrieve = AsyncMock()
        gateway._client._provider.retrieve.return_value = MagicMock(secret_key="admin_secret_key")

        with pytest.raises(TemporaryCredentialIssueError) as exc_info:
            await gateway.create_service_account(policy, expiration)

        assert "network error" in str(exc_info.value)


class _FakeResponseContent:
    """Minimal stand-in for aiohttp's `StreamReader` -- `_AdminResponseDecryptor`
    only ever calls `.content.read(n)`."""

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    async def read(self, n: int) -> bytes:
        chunk = self._data[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk


class _FakeResponse:
    def __init__(self, data: bytes):
        self.content = _FakeResponseContent(data)


def _encrypt_for_test(payload: bytes, secret: bytes, aead_id: int) -> bytes:
    """Test-only encryptor mirroring `_AdminResponseDecryptor`'s wire format
    for AEAD IDs the library doesn't produce itself (2 = PBKDF2+AES-256-GCM)."""
    import os as _os

    from miniopy_async.crypto import _CHUNK_SIZE, _NONCE_LEN, _SALT_LEN, _mark_as_last, _update_nonce_id

    from storage_credentials.clients.minio_admin_client import _AdminResponseDecryptor

    nonce = _os.urandom(_NONCE_LEN)
    salt = _os.urandom(_SALT_LEN)
    key = _AdminResponseDecryptor._derive_key(secret, salt, aead_id)
    padded_nonce = nonce + b"\x00\x00\x00\x00"
    additional_data = _AdminResponseDecryptor._generate_additional_data(
        aead_id, key, padded_nonce
    )

    result = salt + bytes([aead_id]) + nonce
    indices = list(range(0, len(payload), _CHUNK_SIZE)) or [0]
    for count, i in enumerate(indices, start=1):
        chunk_additional_data = additional_data
        if i == indices[-1]:
            chunk_additional_data = _mark_as_last(additional_data)
        chunk_nonce = _update_nonce_id(nonce, count)
        cipher = _AdminResponseDecryptor._cipher(aead_id, key, chunk_nonce)
        cipher.update(chunk_additional_data)
        encrypted, tag = cipher.encrypt_and_digest(payload[i : i + _CHUNK_SIZE])
        result += encrypted + tag
    return result


class TestAdminResponseDecryptor:
    """Unit tests for `_AdminResponseDecryptor` -- the hand-ported crypto
    that lets `list_service_accounts`/`create_service_account` read
    responses RustFS encrypts with AEAD ID 2 (PBKDF2+AES-256-GCM), which
    `miniopy_async`'s own `decrypt()` doesn't support."""

    SECRET = b"admin_secret_key"

    @pytest.mark.asyncio
    async def test_round_trip_aead_id_0_matches_library_encrypt(self):
        """AEAD ID 0 (Argon2id) is delegated to the library's own functions
        -- cross-check against the library's own `encrypt()` directly,
        not just our test helper, to prove the delegation is wired up."""
        from miniopy_async.crypto import encrypt as library_encrypt

        from storage_credentials.clients.minio_admin_client import _AdminResponseDecryptor

        payload = b'{"accounts": [{"accessKey": "ABC"}]}'
        ciphertext = library_encrypt(payload, self.SECRET.decode())

        response = _FakeResponse(ciphertext)
        header = await response.content.read(41)
        decryptor = _AdminResponseDecryptor(header, self.SECRET)
        plaintext = await decryptor.decrypt(response)

        assert plaintext == payload

    @pytest.mark.asyncio
    async def test_round_trip_aead_id_2_pbkdf2(self):
        """AEAD ID 2 (PBKDF2+AES-256-GCM) -- the branch miniopy_async never
        implemented, added specifically for RustFS."""
        from storage_credentials.clients.minio_admin_client import _AdminResponseDecryptor

        payload = b'{"accounts": [{"accessKey": "XYZ", "expiration": "2026-01-01T00:00:00Z"}]}'
        ciphertext = _encrypt_for_test(payload, self.SECRET, aead_id=2)

        response = _FakeResponse(ciphertext)
        header = await response.content.read(41)
        decryptor = _AdminResponseDecryptor(header, self.SECRET)
        plaintext = await decryptor.decrypt(response)

        assert plaintext == payload

    @pytest.mark.asyncio
    async def test_round_trip_multi_chunk_payload(self):
        """A payload spanning more than one 16 KiB chunk -- the only way to
        exercise the `last_chunk` peek-ahead-by-one-byte detection in
        `decrypt()`'s buffering loop. Live-fire testing against RustFS only
        ever sent a couple of small service-account entries and could not
        have caught an off-by-one here."""
        from storage_credentials.clients.minio_admin_client import _AdminResponseDecryptor

        payload = b"x" * (16 * 1024 * 3 + 500)  # a bit over 3 full chunks
        ciphertext = _encrypt_for_test(payload, self.SECRET, aead_id=2)

        response = _FakeResponse(ciphertext)
        header = await response.content.read(41)
        decryptor = _AdminResponseDecryptor(header, self.SECRET)
        plaintext = await decryptor.decrypt(response)

        assert plaintext == payload

    @pytest.mark.asyncio
    async def test_unknown_aead_id_raises(self):
        """An AEAD ID that's neither the library's (0/1) nor ours (2) must
        still fail loudly, not silently return garbage."""
        from storage_credentials.clients.minio_admin_client import _AdminResponseDecryptor

        header = b"\x00" * 32 + bytes([99]) + b"\x00" * 8
        with pytest.raises(ValueError, match="Unknown AEAD ID"):
            _AdminResponseDecryptor(header, self.SECRET)

    def test_short_header_raises(self):
        from storage_credentials.clients.minio_admin_client import _AdminResponseDecryptor

        with pytest.raises(OSError, match="insufficient data"):
            _AdminResponseDecryptor(b"too short", self.SECRET)
