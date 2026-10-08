"""Password-reset requests do no account-dependent work on the request thread.

The response of `POST /api/auth/password-reset/request/` is uniform, so the
only way left to tell a registered email from an unknown one is how long the
request takes. These tests pin down that the request merely queues a job, and
that the job, the backlog bound and the worker pool behave as documented.
"""

import threading
from concurrent.futures import Executor, Future, ThreadPoolExecutor

import pytest
from django.core import mail
from django.core.cache import cache
from django.db import DEFAULT_DB_ALIAS, connections
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from rbac.identity.passwords import reset_dispatcher
from rbac.identity.passwords.email_sender import PasswordResetEmailSender
from rbac.identity.passwords.recovery import PasswordRecoveryService
from rbac.identity.passwords.reset_dispatcher import (
    ConnectionScopedThreadPool,
    PasswordResetDispatcher,
)
from rbac.identity.passwords.token_repository import PasswordResetTokenRepository
from rbac.models import PasswordResetToken
from tests.helpers import InlineExecutor
from utils.logger import logger

LOCMEM_EMAIL = "django.core.mail.backends.locmem.EmailBackend"
SECRET_MARKER = "RAW_RESET_TOKEN_MARKER_must_not_leak"


class RecordingExecutor(Executor):
    """Keep submitted jobs without running them, so a test can run them later."""

    def __init__(self):
        self.jobs = []

    def submit(self, fn, /, *args, **kwargs):
        self.jobs.append((fn, args, kwargs))
        return Future()

    def run_all(self):
        for fn, args, kwargs in self.jobs:
            fn(*args, **kwargs)


class RefusingExecutor(Executor):
    """Behaves like a pool that is shutting down."""

    def submit(self, fn, /, *args, **kwargs):
        raise RuntimeError("cannot schedule new futures after shutdown")


class FailingTokenRepository(PasswordResetTokenRepository):
    """Fails the way a database error would, with the email and a secret in its message."""

    def create_for_user(self, user):
        raise RuntimeError(f"cannot store grant for {user.email}: {SECRET_MARKER}")


class PausingTokenRepository(PasswordResetTokenRepository):
    """Holds the first job inside its transaction until the test releases it."""

    def __init__(self):
        self.first_job_inside = threading.Event()
        self.release_first_job = threading.Event()
        self._calls = 0
        self._calls_lock = threading.Lock()

    def invalidate_all_for_user(self, user):
        with self._calls_lock:
            self._calls += 1
            is_first_call = self._calls == 1
        if is_first_call:
            self.first_job_inside.set()
            self.release_first_job.wait(timeout=10)
        return super().invalidate_all_for_user(user)


class FailingSmtpEmailSender(PasswordResetEmailSender):
    """Fails like `send_mail` against a dead or silent relay, naming the recipient."""

    def __init__(self, error_type: type[OSError]):
        super().__init__()
        self._error_type = error_type

    def _build_context(self, user, raw_token):
        raise self._error_type(f"relay refused {user.email} {raw_token}")


def use_default_dispatcher(monkeypatch, executor: Executor, max_in_flight: int = 5) -> None:
    monkeypatch.setattr(
        reset_dispatcher,
        "default_dispatcher",
        PasswordResetDispatcher(executor=executor, max_in_flight=max_in_flight),
    )


@pytest.fixture
def captured_log_output():
    """Collect every loguru record in the default format, exception and its
    variable values included, the way the stdout sink would print them."""
    messages: list[str] = []
    sink_id = logger.add(messages.append, level="TRACE", diagnose=True, backtrace=True)
    yield messages
    logger.remove(sink_id)


@pytest.fixture
def recording_executor(monkeypatch):
    executor = RecordingExecutor()
    use_default_dispatcher(monkeypatch, executor)
    yield executor


# ---------------- request path ----------------


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
@pytest.mark.parametrize("registered", [True, False])
def test_request_runs_no_query_and_sends_nothing_before_the_job_runs(
    api_client, regular_user, recording_executor, registered
):
    cache.clear()
    mail.outbox = []
    email = regular_user.email if registered else "nobody@example.com"

    with CaptureQueriesContext(connections[DEFAULT_DB_ALIAS]) as queries:
        response = api_client.post(
            reverse("password_reset_request"), data={"email": email}, format="json"
        )

    assert response.status_code == 200
    assert response.json()["smtp_configured"] is True
    assert [query["sql"] for query in queries.captured_queries] == []
    assert len(recording_executor.jobs) == 1
    assert PasswordResetToken.objects.count() == 0
    assert mail.outbox == []

    recording_executor.run_all()

    assert PasswordResetToken.objects.filter(user=regular_user).count() == int(registered)
    assert len(mail.outbox) == int(registered)


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="")
def test_request_without_smtp_queues_nothing(api_client, regular_user, recording_executor):
    cache.clear()

    response = api_client.post(
        reverse("password_reset_request"),
        data={"email": regular_user.email},
        format="json",
    )

    assert response.json()["smtp_configured"] is False
    assert recording_executor.jobs == []


@pytest.mark.django_db(transaction=True)
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
def test_request_delivers_through_a_real_worker_pool(api_client, regular_user, monkeypatch):
    """End to end on real threads: the job sees the committed account, and
    writes the grant and the email from its own connection."""
    cache.clear()
    mail.outbox = []
    pool = ConnectionScopedThreadPool(max_workers=2, thread_name_prefix="password-reset")
    use_default_dispatcher(monkeypatch, pool)

    response = api_client.post(
        reverse("password_reset_request"),
        data={"email": regular_user.email},
        format="json",
    )
    pool.shutdown(wait=True)

    assert response.status_code == 200
    assert PasswordResetToken.objects.filter(user=regular_user).count() == 1
    assert [message.to for message in mail.outbox] == [[regular_user.email]]


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
def test_request_still_answers_when_the_pool_refuses_the_job(
    regular_user, captured_log_output
):
    service = PasswordRecoveryService(
        dispatcher=PasswordResetDispatcher(executor=RefusingExecutor(), max_in_flight=1)
    )

    assert service.request_reset(regular_user.email) == {"smtp_configured": True}
    # The refused job gave its only slot back, so the next one is refused by
    # the executor again, not dropped as a full backlog.
    assert service.request_reset(regular_user.email) == {"smtp_configured": True}

    written = "\n".join(captured_log_output)
    assert written.count("password_reset_job_not_queued error_type=RuntimeError") == 2
    assert "password_reset_job_dropped_backlog_full" not in written
    assert regular_user.email not in written
    assert PasswordResetToken.objects.count() == 0


# ---------------- the job ----------------


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
def test_deliver_reset_replaces_the_grant_of_a_registered_email_and_mails_it(regular_user):
    mail.outbox = []
    prior, _raw_token = PasswordResetTokenRepository().create_for_user(regular_user)

    PasswordRecoveryService().deliver_reset(regular_user.email.upper())

    rows = PasswordResetToken.objects.filter(user=regular_user)
    assert rows.count() == 1
    assert rows.first().pk != prior.pk
    assert [message.to for message in mail.outbox] == [[regular_user.email]]


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
def test_deliver_reset_for_an_unknown_email_writes_and_sends_nothing(regular_user):
    mail.outbox = []

    PasswordRecoveryService().deliver_reset("nobody@example.com")

    assert PasswordResetToken.objects.count() == 0
    assert mail.outbox == []


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
def test_failing_job_is_swallowed_and_logged_without_email_or_secret(
    regular_user, captured_log_output
):
    service = PasswordRecoveryService(
        token_repo=FailingTokenRepository(),
        dispatcher=PasswordResetDispatcher(executor=InlineExecutor(), max_in_flight=1),
    )

    assert service.request_reset(regular_user.email) == {"smtp_configured": True}

    written = "\n".join(captured_log_output)
    assert "password_reset_job_failed error_type=RuntimeError" in written
    assert "create_for_user" in written
    assert regular_user.email not in written
    assert SECRET_MARKER not in written


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
@pytest.mark.parametrize("error_type", [ConnectionRefusedError, TimeoutError])
def test_failing_send_is_logged_without_email_or_token(
    regular_user, captured_log_output, error_type
):
    """The sender's own fail-silent path must not print the link either.

    `TimeoutError` is what the SMTP backend raises once `EMAIL_TIMEOUT` runs
    out against a relay that never answers."""
    service = PasswordRecoveryService(email_sender=FailingSmtpEmailSender(error_type))

    service.deliver_reset(regular_user.email)

    written = "\n".join(captured_log_output)
    assert "password_reset_email_send_failed" in written
    assert f"error_type={error_type.__name__}" in written
    assert regular_user.email not in written
    assert "relay refused" not in written


@pytest.mark.django_db(transaction=True)
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
def test_parallel_jobs_for_one_email_leave_a_single_live_grant(regular_user):
    """The second job waits on the account's row lock until the first commits,
    then deletes the first job's grant: only the newest link works."""
    mail.outbox = []
    token_repo = PausingTokenRepository()
    service = PasswordRecoveryService(token_repo=token_repo)
    pool = ConnectionScopedThreadPool(max_workers=2, thread_name_prefix="password-reset")
    try:
        first = pool.submit(service.deliver_reset, regular_user.email)
        assert token_repo.first_job_inside.wait(timeout=10)
        second = pool.submit(service.deliver_reset, regular_user.email)

        # Without the row lock the second job would run to completion here,
        # while the first is still paused inside its transaction.
        with pytest.raises(TimeoutError):
            second.result(timeout=1)

        token_repo.release_first_job.set()
        first.result(timeout=10)
        second.result(timeout=10)
    finally:
        token_repo.release_first_job.set()
        pool.shutdown(wait=True)

    assert PasswordResetToken.objects.filter(user=regular_user).count() == 1
    assert len(mail.outbox) == 2


# ---------------- backlog bound ----------------


def test_full_backlog_drops_the_job_and_logs_it_once_per_window(captured_log_output):
    release_first_job = threading.Event()
    first_job_started = threading.Event()
    ran = []

    def blocking_job():
        first_job_started.set()
        release_first_job.wait(timeout=5)
        ran.append("first")

    pool = ThreadPoolExecutor(max_workers=1)
    dispatcher = PasswordResetDispatcher(executor=pool, max_in_flight=1)
    try:
        assert dispatcher.dispatch(blocking_job) is True
        assert first_job_started.wait(timeout=5)

        assert dispatcher.dispatch(lambda: ran.append("dropped")) is False
        assert dispatcher.dispatch(lambda: ran.append("dropped again")) is False

        release_first_job.set()
    finally:
        pool.shutdown(wait=True)

    assert ran == ["first"]
    drop_lines = [
        line for line in captured_log_output if "password_reset_job_dropped_backlog_full" in line
    ]
    assert len(drop_lines) == 1


@pytest.mark.parametrize("fails", [False, True])
def test_finished_job_returns_its_slot(fails):
    dispatcher = PasswordResetDispatcher(executor=InlineExecutor(), max_in_flight=1)

    def job():
        if fails:
            raise RuntimeError("boom")

    assert dispatcher.dispatch(job) is True
    assert dispatcher.dispatch(job) is True


# ---------------- worker pool ----------------


@pytest.mark.django_db(transaction=True)
def test_pool_job_runs_on_a_named_worker_and_closes_its_connection(regular_user):
    pool = ConnectionScopedThreadPool(max_workers=1, thread_name_prefix="password-reset")
    seen = {}

    def job():
        seen["thread"] = threading.current_thread().name
        seen["connection"] = connections[DEFAULT_DB_ALIAS]
        seen["user_found"] = type(regular_user).objects.filter(pk=regular_user.pk).exists()

    try:
        pool.submit(job).result(timeout=10)
    finally:
        pool.shutdown(wait=True)

    assert seen["thread"].startswith("password-reset")
    assert seen["thread"] != threading.current_thread().name
    assert seen["user_found"] is True
    assert seen["connection"].connection is None
