import json
import threading
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.shared.models import UserActionEvent
from user_audit import sender as sender_module
from user_audit.sender import UserAuditSender, get_user_audit_sender


def make_event() -> UserActionEvent:
    return UserActionEvent(
        id=str(uuid.uuid4()),
        org_id=1,
        event_time=datetime.now(UTC),
        actor_user_id=5,
        actor_email="someone@example.com",
        action="created",
    )


class FakeAuditor:
    """A real HTTP endpoint on localhost that records every ingest request."""

    def __init__(self):
        self.requests: list[dict] = []
        self.received = threading.Event()
        auditor = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                auditor.requests.append(
                    {
                        "path": self.path,
                        "api_key": self.headers.get("X-API-Key"),
                        "events": json.loads(body),
                    }
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")
                auditor.received.set()

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def auditor(settings):
    fake_auditor = FakeAuditor()
    settings.USER_AUDIT_TRAIL_ENABLED = True
    settings.AUDITOR_URL = fake_auditor.url
    settings.AUDITOR_INGEST_API_KEY = "ingest-key"
    yield fake_auditor
    fake_auditor.close()


def test_send_delivers_events_to_the_user_action_ingest_endpoint(auditor):
    sender = UserAuditSender()
    event = make_event()

    sender.send([event])

    assert auditor.received.wait(timeout=10)
    sender.shutdown()
    [request] = auditor.requests
    assert request["path"] == "/api/audit/user_actions/events"
    assert request["api_key"] == "ingest-key"
    assert [sent["id"] for sent in request["events"]] == [event.id]


def test_send_is_noop_when_switch_off(auditor, settings):
    settings.USER_AUDIT_TRAIL_ENABLED = False
    sender = UserAuditSender()

    sender.send([make_event()])
    sender.shutdown()

    assert auditor.requests == []


def test_send_never_raises_when_client_fails(settings):
    settings.USER_AUDIT_TRAIL_ENABLED = True
    # The client cannot be built without a base URL.
    settings.AUDITOR_URL = None
    sender = UserAuditSender()

    sender.send([make_event()])
    sender.send([make_event()])
    sender.shutdown()


def test_sender_is_recreated_in_a_forked_process(auditor, monkeypatch):
    parent_sender = get_user_audit_sender()
    parent_sender.send([make_event()])
    assert auditor.received.wait(timeout=10)
    assert get_user_audit_sender() is parent_sender

    real_pid = sender_module.os.getpid()
    monkeypatch.setattr(sender_module.os, "getpid", lambda: real_pid + 1)

    child_sender = get_user_audit_sender()
    # The parent's thread does not exist in a child; its inherited atexit hook must return.
    parent_sender.shutdown()
    auditor.received.clear()
    child_sender.send([make_event()])

    assert child_sender is not parent_sender
    assert auditor.received.wait(timeout=10)
    child_sender.shutdown()
