"""backfill_org_storage_credentials against a local HTTP server playing the RustFS admin API.

The server stands in for the storage container only: the command, the provisioning
service, the gateway and the encrypted Secret store all run for real. It answers the
credential check per signing access key and records the secret each `add-user` sets,
so the tests compare what Django stored with what the storage server holds.
"""

import asyncio
import json
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from urllib.parse import parse_qs, urlparse

import pytest
from django.core.management import call_command
from django.db import connections
from loguru import logger
from rbac.models import Organization
from tables.models import Secret

from storage_credentials.clients.minio_admin_client import _HEADER_LENGTH, StorageAdminGateway, _AdminResponseDecryptor
from storage_credentials.constants import SECRET_NAME_ORG_STORAGE_USER
from storage_credentials.resource_names import _org_access_key
from storage_credentials.services.org_credential_store import org_credential_store
from storage_credentials.services.org_provisioning_service import org_storage_provisioning_service

STALE_SECRET = "secret-the-storage-no-longer-holds"
SIGNATURE_DOES_NOT_MATCH = (
    403,
    b'<?xml version="1.0" encoding="UTF-8"?><Error><Code>SignatureDoesNotMatch</Code>'
    b"<Message>The request signature we calculated does not match the signature you provided."
    b"</Message></Error>",
)
INVALID_ACCESS_KEY_ID = (
    403,
    b'<?xml version="1.0" encoding="UTF-8"?><Error><Code>InvalidAccessKeyId</Code>'
    b"<Message>The Access Key Id you provided does not exist in our records.</Message></Error>",
)
ACCESS_DENIED = (
    403,
    b'<?xml version="1.0" encoding="UTF-8"?><Error><Code>AccessDenied</Code>'
    b"<Message>Access Denied.</Message></Error>",
)
INVALID_REQUEST = (400, b'<?xml version="1.0" encoding="UTF-8"?><Error><Code>InvalidRequest</Code></Error>')


class _StreamContent:
    def __init__(self, data: bytes):
        self._data = data

    async def read(self, size: int) -> bytes:
        chunk, self._data = self._data[:size], self._data[size:]
        return chunk


class _EncryptedBody:
    def __init__(self, data: bytes):
        self.content = _StreamContent(data)


def _decrypt(body: bytes, secret: str) -> dict:
    async def run() -> bytes:
        response = _EncryptedBody(body)
        decryptor = _AdminResponseDecryptor(await response.content.read(_HEADER_LENGTH), secret.encode())
        return await decryptor.decrypt(response)

    return json.loads(asyncio.run(run()))


class FakeStorageServer(ThreadingHTTPServer):
    def __init__(self, root_secret: str):
        super().__init__(("127.0.0.1", 0), _FakeStorageHandler)
        self.root_secret = root_secret
        self.url = f"http://127.0.0.1:{self.server_address[1]}"
        # Per access key, the answers to its credential checks in order; the last one repeats.
        self.check_replies: dict[str, list[tuple[int, bytes]]] = {}
        self.default_check_reply: tuple[int, bytes] = (200, b"")
        self.checked_access_keys: list[str] = []
        self.add_user_reply: tuple[int, bytes] = (200, b"")
        # Keys whose checks keep their configured answer after `add-user`; every other key
        # is accepted once the server has set its secret.
        self.rejects_after_provisioning: set[str] = set()
        self.user_secrets: dict[str, str] = {}

    def check_reply(self, access_key: str) -> tuple[int, bytes]:
        replies = self.check_replies.get(access_key)
        if not replies:
            return self.default_check_reply
        return replies.pop(0) if len(replies) > 1 else replies[0]

    def add_user(self, access_key: str, secret: str) -> tuple[int, bytes]:
        if self.add_user_reply[0] == 200:
            self.user_secrets[access_key] = secret
            if access_key not in self.rejects_after_provisioning:
                self.check_replies[access_key] = [(200, b"")]
        return self.add_user_reply


class _FakeStorageHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: FakeStorageServer

    def do_GET(self):
        self._answer()

    def do_PUT(self):
        self._answer()

    def _answer(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        status, reply = 200, b""
        if url.path.endswith("/list-service-accounts"):
            access_key = re.search(r"Credential=([^/]+)/", self.headers["Authorization"]).group(1)
            self.server.checked_access_keys.append(access_key)
            status, reply = self.server.check_reply(access_key)
        elif url.path.endswith("/add-user"):
            secret = _decrypt(body, self.server.root_secret)["secretKey"]
            status, reply = self.server.add_user(query["accessKey"][0], secret)
        self.send_response(status)
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, format, *args):
        pass


@pytest.fixture
def storage_server_accepts_new_users():
    """Overrides the command_tests autouse stub: here the fake server plays the storage side."""


@pytest.fixture
def storage(monkeypatch):
    server = FakeStorageServer(root_secret=org_storage_provisioning_service._root_secret_key)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(org_storage_provisioning_service, "_host", server.url)
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def unreachable_storage(monkeypatch):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setattr(org_storage_provisioning_service, "_host", f"http://127.0.0.1:{port}")


@pytest.fixture
def warnings_logged():
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(message.record["message"]), level="WARNING")
    yield messages
    logger.remove(sink_id)


def _org_with_stored_secret(name: str) -> Organization:
    org = Organization.objects.create(name=name)
    org_credential_store.save(org=org, access_key=_org_access_key(org.id), secret_key=STALE_SECRET)
    return org


def _stored_secret(org: Organization) -> str:
    return org_credential_store.get(org_id=org.id).secret_key


def _run_backfill() -> dict[str, int]:
    stdout = StringIO()
    call_command("backfill_org_storage_credentials", stdout=stdout, stderr=StringIO())
    summary = stdout.getvalue().strip().splitlines()[-1]
    assert summary.startswith("Done: ")
    return {name: int(count) for name, count in (pair.split("=") for pair in summary[6:].split())}


@pytest.mark.django_db
@pytest.mark.parametrize("check_reply", [(200, b""), ACCESS_DENIED], ids=["accepted", "access-denied"])
def test_credentials_the_storage_accepts_are_kept(storage, check_reply):
    org = _org_with_stored_secret("Accepted Org")
    storage.check_replies[_org_access_key(org.id)] = [check_reply]

    counts = _run_backfill()

    assert _stored_secret(org) == STALE_SECRET
    assert _org_access_key(org.id) not in storage.user_secrets
    assert (counts["repaired"], counts["unverified"]) == (0, 0)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("check_reply", "error_code"),
    [(SIGNATURE_DOES_NOT_MATCH, "SignatureDoesNotMatch"), (INVALID_ACCESS_KEY_ID, "InvalidAccessKeyId")],
    ids=["drifted-secret", "unknown-access-key"],
)
def test_credentials_the_storage_rejects_are_reprovisioned(storage, warnings_logged, check_reply, error_code):
    org = _org_with_stored_secret("Drifted Org")
    access_key = _org_access_key(org.id)
    storage.check_replies[access_key] = [check_reply]

    counts = _run_backfill()

    assert storage.user_secrets[access_key] != STALE_SECRET
    assert _stored_secret(org) == storage.user_secrets[access_key]
    assert counts["repaired"] == 1
    assert any(f"org_id={org.id}" in message and error_code in message for message in warnings_logged)
    assert not any(STALE_SECRET in message for message in warnings_logged)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "server_answer",
    ["unreachable", (503, b""), INVALID_REQUEST],
    ids=["unreachable", "server-error", "unexpected-error"],
)
def test_a_check_the_storage_does_not_answer_never_rotates_credentials(request, server_answer):
    if server_answer == "unreachable":
        request.getfixturevalue("unreachable_storage")
    else:
        request.getfixturevalue("storage").default_check_reply = server_answer
    org = _org_with_stored_secret("Unverified Org")

    counts = _run_backfill()

    assert _stored_secret(org) == STALE_SECRET
    assert counts["unverified"] == 1
    assert counts["repaired"] == 0


@pytest.mark.django_db
def test_once_the_storage_does_not_answer_the_remaining_orgs_are_not_checked(storage):
    storage.default_check_reply = (503, b"")
    first_org = _org_with_stored_secret("First Org")
    second_org = _org_with_stored_secret("Second Org")

    counts = _run_backfill()

    assert len(storage.checked_access_keys) == 1
    assert counts["unverified"] == 2
    assert _stored_secret(first_org) == _stored_secret(second_org) == STALE_SECRET


@pytest.mark.django_db
def test_undecryptable_stored_credentials_fail_that_org_without_stopping_the_rest(storage):
    broken_org = _org_with_stored_secret("Broken Org")
    Secret.all_objects.filter(org=broken_org, name=SECRET_NAME_ORG_STORAGE_USER).update(value="not-a-token")
    missing_org = Organization.objects.create(name="Missing Org")

    counts = _run_backfill()

    assert counts["failed"] == 1
    assert org_credential_store.exists(org_id=missing_org.id)
    assert _stored_secret(missing_org) == storage.user_secrets[_org_access_key(missing_org.id)]


@pytest.mark.django_db
def test_an_unexpected_error_while_checking_does_not_fail_the_command(storage, monkeypatch):
    async def broken_check(self):
        raise RuntimeError("unexpected client failure")

    monkeypatch.setattr(StorageAdminGateway, "credential_rejection_code", broken_check)
    org = _org_with_stored_secret("Broken Check Org")
    missing_org = Organization.objects.create(name="Missing Org")

    counts = _run_backfill()

    assert counts["unverified"] == 1
    assert _stored_secret(org) == STALE_SECRET
    assert _stored_secret(missing_org) == storage.user_secrets[_org_access_key(missing_org.id)]


@pytest.mark.django_db
def test_a_failed_repair_keeps_the_stored_secret(storage):
    org = _org_with_stored_secret("Failed Repair Org")
    storage.check_replies[_org_access_key(org.id)] = [SIGNATURE_DOES_NOT_MATCH]
    storage.add_user_reply = INVALID_REQUEST

    counts = _run_backfill()

    assert counts["failed"] == 1
    assert _stored_secret(org) == STALE_SECRET


@pytest.mark.django_db
def test_a_repair_another_process_holds_the_lock_for_is_skipped(storage):
    org = _org_with_stored_secret("Locked Org")
    storage.check_replies[_org_access_key(org.id)] = [SIGNATURE_DOES_NOT_MATCH]
    other_process = connections.create_connection("default")
    try:
        with other_process.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", [org.id])
        counts = _run_backfill()
    finally:
        other_process.close()

    assert (counts["skipped"], counts["repaired"]) == (1, 0)
    assert _stored_secret(org) == STALE_SECRET
    assert _org_access_key(org.id) not in storage.user_secrets


@pytest.mark.django_db
def test_a_repair_another_replica_already_made_is_not_repeated(storage):
    org = _org_with_stored_secret("Already Repaired Org")
    storage.check_replies[_org_access_key(org.id)] = [SIGNATURE_DOES_NOT_MATCH, (200, b"")]

    counts = _run_backfill()

    assert (counts["skipped"], counts["repaired"]) == (1, 0)
    assert _org_access_key(org.id) not in storage.user_secrets


@pytest.mark.django_db
def test_a_key_still_rejected_right_after_repair_fails(storage, warnings_logged):
    org = _org_with_stored_secret("Contested Org")
    access_key = _org_access_key(org.id)
    storage.check_replies[access_key] = [SIGNATURE_DOES_NOT_MATCH]
    storage.rejects_after_provisioning.add(access_key)

    counts = _run_backfill()

    assert (counts["failed"], counts["repaired"]) == (1, 0)
    assert any(
        f"org_id={org.id}" in message and "right after re-provisioning" in message
        for message in warnings_logged
    )
