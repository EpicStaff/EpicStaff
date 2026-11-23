import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from tests.helpers import InlineExecutor
from user_audit import background, recorder
from utils.logger import logger


class RecordingSender:
    def __init__(self):
        self.events = []

    def send(self, events):
        self.events.extend(events)


@pytest.fixture
def sent_events(monkeypatch, settings):
    settings.USER_AUDIT_TRAIL_ENABLED = True
    sender = RecordingSender()
    monkeypatch.setattr(recorder, "get_user_audit_sender", lambda: sender)
    return sender.events


@pytest.fixture(autouse=True)
def inline_background_jobs(monkeypatch):
    """Run the jobs kept off the request thread at once, inside the test's transaction."""
    monkeypatch.setattr(background, "executor", InlineExecutor())


@pytest.fixture
def captured_log_output():
    """Every loguru line written meanwhile, exception and variable values included."""
    messages: list[str] = []
    sink_id = logger.add(messages.append, level="TRACE", diagnose=True, backtrace=True)
    yield messages
    logger.remove(sink_id)


@pytest.fixture
def token_client(admin_acme, acme):
    """A client sending a real bearer token: the row a DELETE names is loaded before
    authentication only for a request that carries credentials, which force_authenticate
    does not send."""
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(admin_acme).access_token}",
        HTTP_X_ORGANIZATION_ID=str(acme.id),
    )
    return client
