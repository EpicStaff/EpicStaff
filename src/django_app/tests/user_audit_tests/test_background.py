"""The worker that records failed sign-ins off the request thread: its bounded backlog, a
refused job, and a failing job's log line, which must never carry the login email.

Application tests against the real module; only the executor is replaced, by one that
holds or refuses jobs, the way `test_password_reset_dispatch` does for its dispatcher.
"""

from concurrent.futures import Executor, Future

import pytest
from django.urls import reverse
from rest_framework import status

from rbac.views import auth
from user_audit import background


class HeldJobs(Executor):
    """Keep each submitted job without running it, so its backlog slot stays taken."""

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


@pytest.fixture
def no_drop_logged_yet(monkeypatch):
    # The drop log is rate-limited per process; another test may have written it.
    monkeypatch.setattr(background, "_drop_logged_at", None)


@pytest.mark.usefixtures("no_drop_logged_yet")
def test_a_full_backlog_drops_jobs_and_logs_it_once(monkeypatch, captured_log_output):
    held = HeldJobs()
    monkeypatch.setattr(background, "executor", held)
    ran = []
    try:
        for _ in range(background._MAX_JOBS_IN_FLIGHT):
            background.run_off_request(lambda: ran.append("queued"))

        background.run_off_request(lambda: ran.append("dropped"))
        background.run_off_request(lambda: ran.append("dropped again"))
    finally:
        # Gives every slot back, so later tests start with an empty backlog.
        held.run_all()

    assert len(held.jobs) == background._MAX_JOBS_IN_FLIGHT
    assert "dropped" not in ran and "dropped again" not in ran
    assert sum("the backlog is full" in line for line in captured_log_output) == 1


@pytest.mark.usefixtures("no_drop_logged_yet")
def test_a_refused_job_is_logged_and_gives_its_slot_back(monkeypatch, captured_log_output):
    monkeypatch.setattr(background, "executor", RefusingExecutor())
    ran = []

    for _ in range(background._MAX_JOBS_IN_FLIGHT + 1):
        background.run_off_request(lambda: ran.append("job"))

    written = "\n".join(captured_log_output)
    assert ran == []
    assert written.count("User action job not queued error_type=RuntimeError") == (
        background._MAX_JOBS_IN_FLIGHT + 1
    )
    # Every refused job gave its slot back, so none was dropped as a full backlog.
    assert "the backlog is full" not in written


@pytest.mark.parametrize("fails", [False, True])
def test_a_finished_job_gives_its_slot_back(fails):
    ran = []

    def job():
        ran.append("job")
        if fails:
            raise RuntimeError("boom")

    for _ in range(background._MAX_JOBS_IN_FLIGHT + 1):
        background.run_off_request(job)

    assert len(ran) == background._MAX_JOBS_IN_FLIGHT + 1


@pytest.mark.django_db
def test_a_failing_sign_in_job_logs_where_it_failed_never_the_email(
    api_client, regular_user, sent_events, monkeypatch, captured_log_output
):
    def failing_actor(user):
        raise RuntimeError(f"no actor for {user.email}")

    monkeypatch.setattr(auth, "_user_actor", failing_actor)

    response = api_client.post(
        reverse("login"), {"email": regular_user.email, "password": "wrong"}, format="json"
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    # Only the recording failure's own line: the refused-login security line names the
    # account on purpose.
    [failure] = [line for line in captured_log_output if "Failed to record user action" in line]
    assert "error_type=RuntimeError" in failure
    assert regular_user.email not in failure
    assert sent_events == []
