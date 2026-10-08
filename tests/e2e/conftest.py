"""Session fixtures for the end-to-end suite against a live EpicStaff stack.

The suite needs a freshly created stack: bootstrap step 1 fails fast when first-setup has
already been used. The bootstrap chain runs once per session, in this order:

1. readiness      - /ht/ is 200 and first-setup still needs a superadmin
2. superadmin     - POST /api/auth/first-setup/ -> superadmin JWT and the organization
                    (used for steps 3-4 only; `superadmin_client` logs in for a fresh one)
3. custom role    - POST /api/admin/roles/ with the minimum permissions the suite needs
4. user           - POST /api/admin/users/ in the organization with that role
5. user login     - POST /api/auth/login/ once (login is throttled per IP + email)
6. api key        - POST /api/profile/api-keys/ with the user's JWT
7. switch to key  - validate the key and read the effective permissions with it

Every step's response is recorded (credentials redacted) on `Bootstrap.steps`, so
test_auth_rbac.py asserts on them without repeating throttled or one-shot calls. Every
credential the suite creates is registered with `helpers.redaction`, and every log record is
scrubbed of them (see `scrubbing_record_factory`).

After the bootstrap, `stack_warm_up` (autouse) runs flow A once. It is the only place that
retries the run-session listener gate (see its docstring); every test runs after it.

Environment:
    E2E_BASE_URL      nginx base URL, default http://localhost
    E2E_TIMINGS_DIR   where timings.json is written, default tests/e2e/.timings; a
                      stack_ready.json from scripts/wait_for_stack.py in it is merged in
"""

import json
import logging
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from helpers.api import ApiClient
from helpers.bootstrap import (
    API_KEY_PREFIX,
    EMAIL_DOMAIN,
    RUNNER_ROLE_PERMISSIONS,
    Bootstrap,
    StepResponse,
    new_password,
    unique_suffix,
)
from helpers.redaction import protect, redact_url, scrub
from helpers.flows import assert_session_ended, create_python_flow, start_session
from helpers.polling import session_diagnostics, wait_for_session_status

logger = logging.getLogger("e2e.bootstrap")
# httpx and httpcore log URLs and headers without redaction; helpers.api logs requests instead.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_default_record_factory = logging.getLogRecordFactory()


def scrubbing_record_factory(*args: object, **keyword_arguments: object) -> logging.LogRecord:
    """Create every log record with registered secrets already scrubbed from its message."""
    record = _default_record_factory(*args, **keyword_arguments)
    try:
        message = record.getMessage()
    except (TypeError, ValueError):
        # Malformed format arguments: leave the record for logging's own error report.
        return record
    record.msg = scrub(message)
    record.args = ()
    return record


logging.setLogRecordFactory(scrubbing_record_factory)

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost").rstrip("/")
# scripts/wait_for_stack.py resolves the same default.
TIMINGS_DIR = Path(
    os.environ.get("E2E_TIMINGS_DIR") or Path(__file__).resolve().parent / ".timings"
)

# SessionManagerService stores "Data was sent and received by (N) listeners, but (2)
# required." when the session did not reach exactly crew + manager.
LISTENER_GATE_PATTERN = re.compile(r"received by \((\d+)\) listeners")
REQUIRED_LISTENERS = 2
LISTENER_GATE_RETRY_SECONDS = 60
WARM_UP_RUN_TIMEOUT_SECONDS = 300


class Timings:
    """Named durations collected during the run, written to timings.json at session end."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.measurements: dict[str, float] = {}

    def record(self, name: str, seconds: float) -> None:
        self.measurements[name] = round(seconds, 2)
        logger.info("timing %s = %.2fs", name, seconds)

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        started = time.monotonic()
        yield
        self.record(name, time.monotonic() - started)

    def write(self) -> Path:
        report: dict[str, float] = {}
        stack_ready_file = self.directory / "stack_ready.json"
        if stack_ready_file.exists():
            report.update(json.loads(stack_ready_file.read_text()))
        report.update(self.measurements)
        self.directory.mkdir(parents=True, exist_ok=True)
        timings_file = self.directory / "timings.json"
        timings_file.write_text(json.dumps(report, indent=2, sort_keys=True))
        return timings_file


@contextmanager
def bootstrap_step(number: int, name: str, bootstrap: Bootstrap | None = None) -> Iterator[None]:
    """Re-raise any failure inside the block as one that names the bootstrap step.

    The message carries the exception type, the redacted URL of a failed request and the
    last recorded (redacted) step. No traceback (`pytrace=False`) and no chained context
    (`from None`): frames and their locals would be the one place left to leak credentials.
    """
    try:
        yield
    except Exception as error:
        details = [f"bootstrap step {number} ({name}): {type(error).__name__}: {scrub(str(error))}"]
        if isinstance(error, httpx.RequestError):
            details.append(f"request: {error.request.method} {redact_url(str(error.request.url))}")
        if bootstrap is not None:
            details.append(bootstrap.describe_last_step())
        raise pytest.fail.Exception("\n".join(details), pytrace=False) from None


@pytest.fixture(scope="session")
def timings() -> Iterator[Timings]:
    collector = Timings(TIMINGS_DIR)
    yield collector
    written = collector.write()
    logger.info("timings written to %s", written)


@pytest.fixture(scope="session")
def anonymous_client() -> Iterator[ApiClient]:
    client = ApiClient.anonymous(BASE_URL)
    yield client
    client.close()


@pytest.fixture(scope="session")
def bootstrap(anonymous_client: ApiClient, timings: Timings) -> Bootstrap:
    result = Bootstrap()
    suffix = unique_suffix()
    started = time.monotonic()

    with bootstrap_step(1, "readiness", result):
        health = anonymous_client.get("/ht/")
        result.steps["health"] = StepResponse(health.status_code, None)
        setup_state = result.record("first_setup_state", anonymous_client.get("/api/auth/first-setup/"))
        if not setup_state["needs_setup"]:
            if setup_state.get("setup_mode") != "open":
                reason = (
                    f"first-setup over HTTP is closed (setup_mode={setup_state.get('setup_mode')!r}); "
                    "the e2e stack needs DJANGO_FIRST_SETUP_MODE=open"
                )
            else:
                reason = (
                    "DB is not fresh: a user already exists. Reset the stack with "
                    "`down -v --remove-orphans` and `up -d`"
                )
            raise AssertionError(reason)

    with bootstrap_step(2, "superadmin first-setup", result):
        result.superadmin_email = f"e2e-admin-{suffix}@{EMAIL_DOMAIN}"
        result.superadmin_password = new_password()
        first_setup = result.record(
            "first_setup",
            anonymous_client.post(
                "/api/auth/first-setup/",
                json={"email": result.superadmin_email, "password": result.superadmin_password},
                expect=201,
            ),
        )
        result.superadmin_user_id = first_setup["user"]["id"]
        result.org_id = first_setup["organization"]["id"]

    superadmin = ApiClient.with_jwt(BASE_URL, first_setup["access"], result.org_id)
    del first_setup
    try:
        with bootstrap_step(3, "custom role", result):
            role = result.record(
                "custom_role",
                superadmin.post(
                    "/api/admin/roles/",
                    json={
                        "org_id": result.org_id,
                        "name": f"E2E Runner {suffix}",
                        "permissions": RUNNER_ROLE_PERMISSIONS,
                    },
                    expect=201,
                ),
            )
            result.role_id = role["id"]

        user_password = new_password()
        with bootstrap_step(4, "user", result):
            result.user_email = f"e2e-user-{suffix}@{EMAIL_DOMAIN}"
            user = result.record(
                "user",
                superadmin.post(
                    "/api/admin/users/",
                    json={
                        "email": result.user_email,
                        "password": user_password,
                        "organization_id": result.org_id,
                        "role_id": result.role_id,
                    },
                    expect=201,
                ),
            )
            result.user_id = user["id"]
    finally:
        superadmin.close()

    with bootstrap_step(5, "user login", result):
        login = result.record(
            "user_login",
            anonymous_client.post(
                "/api/auth/login/",
                json={"email": result.user_email, "password": user_password},
            ),
        )

    user_with_jwt = ApiClient.with_jwt(BASE_URL, login["access"])
    del login
    try:
        with bootstrap_step(6, "api key", result):
            api_key = result.record(
                "api_key",
                user_with_jwt.post(
                    "/api/profile/api-keys/",
                    json={"name": "e2e", "expires_in_days": 1},
                    expect=201,
                ),
            )
            result.user_api_key = api_key["api_key"]
            del api_key
            result.api_key_has_expected_prefix = result.user_api_key.startswith(API_KEY_PREFIX)
    finally:
        user_with_jwt.close()

    user_with_key = ApiClient.with_api_key(BASE_URL, result.user_api_key, result.org_id)
    try:
        with bootstrap_step(7, "switch to api key", result):
            result.record("api_key_validate", user_with_key.get("/api/auth/api-key/validate/"))
            result.record("permissions_me", user_with_key.get("/api/permissions/me/"))
    finally:
        user_with_key.close()

    timings.record("bootstrap_seconds", time.monotonic() - started)
    return result


@pytest.fixture(scope="session")
def org_id(bootstrap: Bootstrap) -> int:
    return bootstrap.org_id


@pytest.fixture(scope="session")
def role_id(bootstrap: Bootstrap) -> int:
    return bootstrap.role_id


@pytest.fixture(scope="session")
def user_id(bootstrap: Bootstrap) -> int:
    return bootstrap.user_id


@pytest.fixture(scope="session")
def superadmin_client(bootstrap: Bootstrap, anonymous_client: ApiClient) -> Iterator[ApiClient]:
    """Superadmin JWT, freshly logged in. Only for admin-only operations.

    The first-setup token is not reused: access tokens live 15 minutes, shorter than a
    full run. One login per session stays well inside the 5/min per IP + email throttle.
    """
    with bootstrap_step(9, "superadmin login", bootstrap):
        login = protect(
            anonymous_client.post(
                "/api/auth/login/",
                json={"email": bootstrap.superadmin_email, "password": bootstrap.superadmin_password},
            ).json()
        )
    client = ApiClient.with_jwt(BASE_URL, login["access"], bootstrap.org_id)
    del login
    yield client
    client.close()


@pytest.fixture(scope="session")
def user_client(bootstrap: Bootstrap) -> Iterator[ApiClient]:
    """The test user's API key in the bootstrap organization: what every test uses."""
    client = ApiClient.with_api_key(BASE_URL, bootstrap.user_api_key, bootstrap.org_id)
    yield client
    client.close()


def listener_count_of_gate_failure(session: dict) -> int | None:
    """The receiver count when the session failed the listener gate, else None."""
    if session.get("status") != "error":
        return None
    reason = (session.get("status_data") or {}).get("reason") or ""
    match = LISTENER_GATE_PATTERN.search(reason)
    return int(match.group(1)) if match else None


def start_warm_up_session(client: ApiClient, graph_id: int) -> int:
    """Start flow A, retrying only while fewer than crew + manager have subscribed."""
    deadline = time.monotonic() + LISTENER_GATE_RETRY_SECONDS
    delay = 2.0
    while True:
        session_id = start_session(client, graph_id, {"a": 2, "b": 3})["session_id"]
        session = client.get(f"/api/sessions/{session_id}/").json()
        listener_count = listener_count_of_gate_failure(session)
        if listener_count is None:
            return session_id
        if listener_count > REQUIRED_LISTENERS:
            raise AssertionError(
                f"too many listeners: the session reached {listener_count} subscribers, "
                f"{REQUIRED_LISTENERS} required. Is another crew or manager on the same "
                f"Redis?\n{session_diagnostics(client, session_id)}"
            )
        if time.monotonic() + delay > deadline:
            raise AssertionError(
                f"listener gate still closed after {LISTENER_GATE_RETRY_SECONDS}s "
                f"(crew and manager must both subscribe):\n{session_diagnostics(client, session_id)}"
            )
        logger.info("session %s hit the listener gate; retrying in %.0fs", session_id, delay)
        time.sleep(delay)
        delay = min(delay * 2, 10.0)


@pytest.fixture(scope="session", autouse=True)
def stack_warm_up(user_client: ApiClient, timings: Timings) -> None:
    """Run flow A once before any test.

    Crew and manager subscribe to the session channel on their own schedule, after /ht/ is
    already 200, and a run-session that reaches fewer than both comes back 201 with the
    session in `error`. Only this warm-up retries that case; afterwards every test treats
    it as a failure. The first run also pays the sandbox venv cold start. Autouse so no
    test that starts a session can forget to depend on it.
    """
    started = time.monotonic()
    with bootstrap_step(8, "warm-up run"):
        flow = create_python_flow(user_client, f"e2e-warm-up-{unique_suffix()}")
        session_id = start_warm_up_session(user_client, flow.graph_id)
        status = wait_for_session_status(user_client, session_id, WARM_UP_RUN_TIMEOUT_SECONDS)
        assert_session_ended(user_client, session_id, status)
    timings.record("warm_up_seconds", time.monotonic() - started)
