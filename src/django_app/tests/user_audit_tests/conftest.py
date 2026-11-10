import pytest

from tests.helpers import InlineExecutor
from user_audit import background, recorder


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
