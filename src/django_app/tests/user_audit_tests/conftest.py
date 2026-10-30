import pytest

from user_audit import recorder


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
