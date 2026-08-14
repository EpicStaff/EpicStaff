"""
Two distinct token paths are used deliberately:

* `mint_audit_token()` goes through Django's real `POST /api/audit/token/`,
  exercising the genuine RBAC -> claims path. Use it for anything that
  asserts on how permissions become claims.
* `forge_audit_token()` signs a token locally with the shared `JWT_SECRET`.
  Use it only where a test needs an exact claim combination that the real
  endpoint can't be asked for on demand (a read-only token, a foreign
  org_id, a specific retention window). This is how `auditor`'s own gating
  gets tested independently of Django's seeding.

Signing is implemented against hmac/hashlib rather than PyJWT so this suite
gains no new dependency (integration_tests/requirements.txt is UTF-16 and
intentionally minimal).
"""

import base64
import hashlib
import hmac
import json
import random
import time
from datetime import datetime, timedelta, timezone

import requests
from loguru import logger

from utils.variables import (
    AUDITOR_INGEST_API_KEY,
    AUDITOR_URL,
    AUDIT_JWT_SECRET,
    AUDIT_TEST_ORG_ID,
    DJANGO_URL,
)
from utils.utils import get_headers, validate_response

# Audit writes travel crew -> AuditClient (batched ~1.5s) -> auditor ->
# OpenSearch (refresh interval ~1s), so a row is never readable the instant
# its session ends. Every read-after-run assertion has to poll.
AUDIT_VISIBILITY_TIMEOUT_SECONDS = 60
AUDIT_POLL_INTERVAL_SECONDS = 2.0


# --------------------------------------------------------------------------
# tokens
# --------------------------------------------------------------------------


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode_jwt_payload(token: str) -> dict:
    """Decode a JWT's claims without verifying - for assertions only."""
    payload_segment = token.split(".")[1]
    padding = "=" * (-len(payload_segment) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_segment + padding))


def forge_audit_token(
    org_id: int,
    actions: list[str],
    retention_days: int = 0,
    ttl_seconds: int = 600,
) -> str:
    """
    Locally sign an auditor-shaped HS256 token. Mirrors the claim set built
    by django_app's AuditTokenView (org_id/actions/retention_days/iat/exp).
    """
    now = datetime.now(timezone.utc)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "org_id": org_id,
        "actions": actions,
        "retention_days": retention_days,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode())
    ).encode()
    signature = hmac.new(
        AUDIT_JWT_SECRET.encode(), signing_input, hashlib.sha256
    ).digest()
    return signing_input.decode() + "." + _b64url(signature)


def get_audit_org_id() -> int:
    """
    Resolve the org to audit against. Explicit env override wins; otherwise
    take the first org from the superadmin listing (the first-setup admin
    this suite logs in as is a superadmin).
    """
    if AUDIT_TEST_ORG_ID:
        return int(AUDIT_TEST_ORG_ID)

    response = requests.get(f"{DJANGO_URL}/admin/organizations/", headers=get_headers())
    validate_response(response)
    organizations = response.json()
    assert organizations, "No organizations exist - cannot run audit tests"
    return organizations[0]["id"]


def mint_audit_token(org_id: int) -> dict:
    """Real path: Django mints the token auditor will accept. Returns the body."""
    headers = {**get_headers(), "X-Organization-Id": str(org_id)}
    response = requests.post(f"{DJANGO_URL}/audit/token/", headers=headers)
    validate_response(response)
    return response.json()


def audit_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------
# auditor reads
# --------------------------------------------------------------------------


def query_sessions(token: str, **params) -> requests.Response:
    return requests.get(
        f"{AUDITOR_URL}/api/audit/sessions",
        headers=audit_headers(token),
        params=params or None,
        timeout=30,
    )


def get_session_tree(token: str, session_id: int) -> requests.Response:
    return requests.get(
        f"{AUDITOR_URL}/api/audit/sessions/{session_id}/tree",
        headers=audit_headers(token),
        timeout=30,
    )


def create_export_job(
    token: str, export_format: str = "csv", detail: str = "base"
) -> requests.Response:
    return requests.post(
        f"{AUDITOR_URL}/api/audit/export",
        headers={**audit_headers(token), "Content-Type": "application/json"},
        json={"format": export_format, "detail": detail},
        timeout=30,
    )


def fetch_export(token: str, job_id: str) -> requests.Response:
    return requests.get(
        f"{AUDITOR_URL}/api/audit/export/{job_id}",
        headers=audit_headers(token),
        timeout=30,
    )


def wait_for_export(
    token: str, job_id: str, timeout: int = AUDIT_VISIBILITY_TIMEOUT_SECONDS
) -> requests.Response:
    """
    Export is an async job: the poll endpoint answers `{"status": "pending"}`
    as JSON until the job finishes, then serves the file body itself (and
    500s if the job failed). Poll until it stops being a status envelope.
    """
    deadline = time.time() + timeout
    last_status = None
    while time.time() < deadline:
        response = fetch_export(token, job_id)
        if response.status_code >= 500:
            raise AssertionError(f"Export job {job_id} failed: {response.text[:300]}")
        try:
            envelope = response.json()
        except ValueError:
            return response  # a real file body, not a status envelope
        if isinstance(envelope, dict) and set(envelope) == {"status"}:
            last_status = envelope["status"]
            time.sleep(AUDIT_POLL_INTERVAL_SECONDS)
            continue
        return response  # JSON-format export finished

    raise AssertionError(
        f"Export job {job_id} never completed within {timeout}s (last status: {last_status})"
    )


# --------------------------------------------------------------------------
# auditor writes (direct ingest, bypassing crew)
# --------------------------------------------------------------------------


def synthetic_session_id() -> int:
    """
    A session id far outside the range Postgres will realistically assign,
    so directly-ingested fixtures can never collide with a real run's rows.
    """
    return random.randint(900_000_000, 999_999_999)


def make_audit_event(
    *,
    org_id: int,
    session_id: int,
    event_id: str,
    kind: str = "session",
    status: str = "completed",
    event_time: datetime | None = None,
    **overrides,
) -> dict:
    event = {
        "id": event_id,
        "org_id": org_id,
        "session_id": session_id,
        "kind": kind,
        "status": status,
        "event_time": (event_time or datetime.now(timezone.utc)).isoformat(),
    }
    event.update(overrides)
    return event


def ingest_events(events: list[dict], api_key: str | None = None) -> requests.Response:
    """POST straight to auditor's ingest endpoint, as crew's AuditClient does."""
    key = AUDITOR_INGEST_API_KEY if api_key is None else api_key
    return requests.post(
        f"{AUDITOR_URL}/api/audit/events",
        headers={"X-API-Key": key, "Content-Type": "application/json"},
        json=events,
        timeout=30,
    )


# --------------------------------------------------------------------------
# waiting
# --------------------------------------------------------------------------


def wait_for_audit_tree(
    token: str,
    session_id: int,
    min_items: int = 1,
    required_kinds: set[str] | None = None,
    required_event_names: set[str] | None = None,
    timeout: int = AUDIT_VISIBILITY_TIMEOUT_SECONDS,
) -> list[dict]:
    """
    Poll a session's audit tree until it is complete enough to assert on.

    `required_kinds` matters more than `min_items` for a real run: the
    kind='session' identity doc and the "Session Start" event both land
    immediately (top of run_session), so `min_items`/`required_kinds` alone
    can be satisfied well before the session actually finishes - node rows
    land on their own batch flush too. Pass `required_event_names` (e.g.
    {"Session End"}) when the test specifically needs to wait for the
    session's outcome, not just its early rows - kind="event" is satisfied
    almost instantly by "Session Start" alone, so kind membership by itself
    can't distinguish "just started" from "actually finished".

    Fails with the last-seen state rather than a bare timeout, so a partial
    trail is diagnosable from the assertion message alone.
    """
    deadline = time.time() + timeout
    items: list[dict] = []
    while time.time() < deadline:
        response = get_session_tree(token, session_id)
        if response.ok:
            items = response.json()["items"]
            kinds = {i["kind"] for i in items}
            event_names = {i["name"] for i in items if i["kind"] == "event"}
            if (
                len(items) >= min_items
                and (required_kinds is None or required_kinds <= kinds)
                and (
                    required_event_names is None
                    or required_event_names <= event_names
                )
            ):
                return items
        else:
            logger.debug(f"tree poll returned {response.status_code}: {response.text[:200]}")
        time.sleep(AUDIT_POLL_INTERVAL_SECONDS)

    raise AssertionError(
        f"Audit tree for session {session_id} was still incomplete after {timeout}s: "
        f"{len(items)} row(s) (wanted >={min_items}), kinds seen "
        f"{sorted({i.get('kind') for i in items})}"
        + (f", wanted kinds {sorted(required_kinds)}" if required_kinds else "")
        + (
            f", wanted events {sorted(required_event_names)}"
            if required_event_names
            else ""
        )
    )


def wait_for_audit_event_id(
    token: str,
    session_id: int,
    event_id: str,
    timeout: int = AUDIT_VISIBILITY_TIMEOUT_SECONDS,
) -> dict:
    """Poll until one specific event id is readable back, and return it."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = get_session_tree(token, session_id)
        if response.ok:
            for item in response.json()["items"]:
                if item["id"] == event_id:
                    return item
        time.sleep(AUDIT_POLL_INTERVAL_SECONDS)

    raise AssertionError(
        f"Event {event_id} (session {session_id}) never became visible within {timeout}s"
    )


def auditor_is_available() -> bool:
    try:
        return requests.get(f"{AUDITOR_URL}/health", timeout=5).ok
    except requests.RequestException:
        return False


def ingest_key_configured() -> bool:
    return bool(AUDITOR_INGEST_API_KEY)


def jwt_secret_configured() -> bool:
    return bool(AUDIT_JWT_SECRET)
