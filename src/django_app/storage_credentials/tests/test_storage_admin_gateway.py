"""StorageAdminGateway against a local HTTP server playing MinIO/RustFS's admin API.

The server records every request and decrypts request bodies with the admin secret,
the way the real storage server does, so these tests pin what the gateway actually
sends and how it reacts to the answers - not how it wires up its HTTP client.
"""

import json
import re
import socket
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from aiohttp import web
from loguru import logger

from storage_credentials.clients.minio_admin_client import (
    _HEADER_LENGTH,
    StorageAdminGateway,
    _AdminResponseDecryptor,
)
from storage_credentials.exceptions import (
    StorageCredentialConfigError,
    TemporaryCredentialIssueError,
    TemporaryCredentialListError,
)

pytestmark = pytest.mark.asyncio

ADMIN_SECRET = "admin_secret_key"
POLICY = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": ["*"]}]}


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

    async def test_unknown_aead_id_raises(self):
        """An AEAD ID that's neither the library's (0/1) nor ours (2) must
        still fail loudly, not silently return garbage."""
        from storage_credentials.clients.minio_admin_client import _AdminResponseDecryptor

        header = b"\x00" * 32 + bytes([99]) + b"\x00" * 8
        with pytest.raises(ValueError, match="Unknown AEAD ID"):
            _AdminResponseDecryptor(header, self.SECRET)

    async def test_short_header_raises(self):
        from storage_credentials.clients.minio_admin_client import _AdminResponseDecryptor

        with pytest.raises(OSError, match="insufficient data"):
            _AdminResponseDecryptor(b"too short", self.SECRET)



class FakeStorageServer:
    def __init__(self):
        self.requests: list[dict] = []
        self.replies: list[tuple[int, bytes]] = []

    async def handle(self, request: web.Request) -> web.Response:
        self.requests.append(
            {"method": request.method, "path": request.path, "query": dict(request.query), "body": await request.read()}
        )
        status, body = self.replies.pop(0) if self.replies else (200, b"")
        return web.Response(status=status, body=body)

    async def decrypted_body(self, request: dict) -> dict:
        body = request["body"]
        response = _FakeResponse(body)
        decryptor = _AdminResponseDecryptor(await response.content.read(_HEADER_LENGTH), ADMIN_SECRET.encode())
        return json.loads(await decryptor.decrypt(response))


@pytest_asyncio.fixture
async def server():
    fake = FakeStorageServer()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", fake.handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    fake.url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    yield fake
    await runner.cleanup()


@pytest_asyncio.fixture
async def gateway(server):
    gateway = StorageAdminGateway(host=server.url, access_key="admin_access_key", secret_key=ADMIN_SECRET)
    yield gateway
    await gateway.close()


@pytest.fixture
def error_logs():
    records: list[str] = []
    sink_id = logger.add(records.append, level="ERROR")
    yield records
    logger.remove(sink_id)


def _unused_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.parametrize("host", ["minio.example.com:9000", ""], ids=["no-scheme", "empty"])
async def test_a_storage_endpoint_without_a_scheme_is_a_configuration_error(host):
    with pytest.raises(StorageCredentialConfigError):
        StorageAdminGateway(host=host, access_key="key", secret_key="secret")


async def test_service_account_is_minted_with_fresh_keys_scoped_to_the_policy(gateway, server):
    before = datetime.now(UTC)

    access_key, secret_key = await gateway.create_service_account(POLICY, timedelta(hours=1))
    second_access_key, _ = await gateway.create_service_account(POLICY, timedelta(hours=1))

    first_request = server.requests[0]
    assert (first_request["method"], first_request["path"]) == ("PUT", "/minio/admin/v3/add-service-account")
    sent = await server.decrypted_body(first_request)
    assert {key: sent[key] for key in ("status", "accessKey", "secretKey", "policy")} == {
        "status": "enabled",
        "accessKey": access_key,
        "secretKey": secret_key,
        "policy": POLICY,
    }
    expires = datetime.strptime(sent["expiration"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert timedelta(minutes=59) < expires - before < timedelta(minutes=61)
    assert re.fullmatch(r"[A-Za-z0-9]{20}", access_key)
    assert len(secret_key) == 40
    assert second_access_key != access_key


async def test_service_account_without_expiration_sends_none(gateway, server):
    await gateway.create_service_account(POLICY)

    assert "expiration" not in await server.decrypted_body(server.requests[0])


async def test_transient_server_errors_are_retried_until_the_storage_answers(gateway, server):
    server.replies = [(503, b""), (502, b"")]

    await gateway.create_service_account(POLICY, timedelta(hours=1))

    assert len(server.requests) == 3


@pytest.mark.parametrize(
    ("replies", "expected_requests"),
    [([(400, b'{"Code":"InvalidRequest"}')], 1), ([(500, b"")] * 5, 5)],
    ids=["rejected-not-retried", "server-error-after-every-retry"],
)
async def test_a_refused_service_account_is_reported_without_backend_detail(
    gateway, server, error_logs, replies, expected_requests
):
    server.replies = list(replies)

    with pytest.raises(TemporaryCredentialIssueError) as error:
        await gateway.create_service_account(POLICY, timedelta(hours=1))

    assert str(error.value) == TemporaryCredentialIssueError.default_detail
    assert len(server.requests) == expected_requests
    assert error_logs


async def test_an_unreachable_storage_is_reported_without_its_address(error_logs):
    host = f"http://127.0.0.1:{_unused_port()}"
    gateway = StorageAdminGateway(host=host, access_key="admin_access_key", secret_key=ADMIN_SECRET)

    try:
        with pytest.raises(TemporaryCredentialIssueError) as error:
            await gateway.create_service_account(POLICY, timedelta(hours=1))
    finally:
        await gateway.close()

    detail = str(error.value)
    assert detail == TemporaryCredentialIssueError.default_detail
    assert "127.0.0.1" not in detail
    assert "network error" in "".join(error_logs)


@pytest.mark.parametrize("aead_id", [0, 2], ids=["argon2id", "pbkdf2-rustfs"])
async def test_service_accounts_are_listed_from_the_encrypted_reply(gateway, server, aead_id):
    accounts = [{"accessKey": "ABC", "expiration": "2026-01-01T00:00:00Z"}]
    payload = json.dumps({"accounts": accounts}).encode()
    if aead_id == 0:
        from miniopy_async.crypto import encrypt

        server.replies = [(200, encrypt(payload, ADMIN_SECRET))]
    else:
        server.replies = [(200, _encrypt_for_test(payload, ADMIN_SECRET.encode(), aead_id=2))]

    assert await gateway.list_service_accounts("org_7") == accounts
    assert server.requests[0]["query"]["user"] == "org_7"


async def test_an_unreadable_listing_is_a_list_error(gateway, server):
    server.replies = [(200, b"not encrypted at all")]

    with pytest.raises(TemporaryCredentialListError):
        await gateway.list_service_accounts("org_7")


async def test_removing_a_user_that_is_already_gone_succeeds(gateway, server):
    """RustFS answers a missing user with 500 InternalError instead of 404."""
    server.replies = [(500, b'{"Code":"InternalError","Message":"user does not exist"}')] * 5

    await gateway.remove_user("org_7")
