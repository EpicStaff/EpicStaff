import socket

import httpx
import pytest

from conftest import load_tool_main

notify_module = load_tool_main("notification_tool")
notify_main = notify_module.main


@pytest.fixture(autouse=True)
def _reset_globals():
    names = ["api_key", "api_base_url"]
    for name in names:
        if hasattr(notify_module, name):
            delattr(notify_module, name)
    yield
    for name in names:
        if hasattr(notify_module, name):
            delattr(notify_module, name)


_ORIGINAL_HTTPX_CLIENT = httpx.Client


def _mock_httpx_client(monkeypatch, handler):
    def _fake_client(**kwargs):
        return _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", _fake_client)


def _mock_public_dns(monkeypatch, public_ip="93.184.216.34"):
    """The SSRF guard resolves the webhook host via `socket.getaddrinfo`
    before ever opening an httpx connection. Real DNS lookups for
    made-up test hostnames are slow/flaky in a sandboxed CI network, so
    tests that need the guard to PASS (target really is public) mock the
    resolution to a known-public IP instead of hitting real DNS."""
    original_getaddrinfo = socket.getaddrinfo

    def _fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (public_ip, 443))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    return original_getaddrinfo


class TestNotificationToolEmail:
    def test_email_happy_path(self, monkeypatch):
        notify_module.api_key = "test-key"

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-Api-Key"] == "test-key"
            assert request.method == "POST"
            assert request.url.path == "/api/notify/email/"
            import json as _json

            payload = _json.loads(request.content)
            assert payload["to"] == "ops@example.com"
            assert payload["message"] == "Build done"
            return httpx.Response(200, json={"sent": True})

        _mock_httpx_client(monkeypatch, handler)

        result = notify_main(
            message="Build done", channel="email", target="ops@example.com"
        )

        assert result.startswith("Notification email sent to ops@example.com")

    def test_email_missing_api_key_returns_error(self):
        result = notify_main(
            message="Build done", channel="email", target="ops@example.com"
        )
        assert result.startswith("Error:")
        assert "api_key" in result

    def test_email_api_failure_returns_error(self, monkeypatch):
        notify_module.api_key = "test-key"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, text="mail server down")

        _mock_httpx_client(monkeypatch, handler)

        result = notify_main(
            message="Build done", channel="email", target="ops@example.com"
        )
        assert result.startswith("Error:")
        assert "502" in result


class TestNotificationToolWebhook:
    def test_webhook_happy_path(self, monkeypatch):
        _mock_public_dns(monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            import json as _json

            payload = _json.loads(request.content)
            assert payload == {"message": "Build done"}
            return httpx.Response(200, json={"ok": True})

        _mock_httpx_client(monkeypatch, handler)

        result = notify_main(
            message="Build done",
            channel="webhook",
            target="https://hooks.example.com/notify",
        )

        assert result.startswith("Notification sent to webhook")

    def test_webhook_refuses_loopback_address(self):
        result = notify_main(
            message="Build done", channel="webhook", target="http://127.0.0.1/hook"
        )
        assert result.startswith("Error:")
        assert "SSRF" in result

    def test_webhook_refuses_link_local_metadata_address(self):
        result = notify_main(
            message="Build done",
            channel="webhook",
            target="http://169.254.169.254/hook",
        )
        assert result.startswith("Error:")
        assert "SSRF" in result

    def test_webhook_refuses_redirect_to_private_ip(self, monkeypatch):
        """A public webhook URL that 302-redirects to a private/internal
        address must not be followed (TOCTOU SSRF via redirect) -- the
        pre-request _ssrf_guard only validates the initial URL, so
        follow_redirects must be disabled and any 3xx response surfaced
        as a refusal instead of transparently followed."""
        _mock_public_dns(monkeypatch)
        request_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            request_count["n"] += 1
            # If httpx ever followed the redirect, a second request would
            # be issued against the redirected (private) target.
            return httpx.Response(
                302, headers={"Location": "http://127.0.0.1/internal-hook"}
            )

        _mock_httpx_client(monkeypatch, handler)

        result = notify_main(
            message="Build done",
            channel="webhook",
            target="https://hooks.example.com/notify",
        )

        assert result.startswith("Error:")
        assert "redirect" in result
        assert "302" in result
        assert "127.0.0.1" in result
        assert request_count["n"] == 1

    def test_webhook_failure_status_returns_error(self, monkeypatch):
        _mock_public_dns(monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        _mock_httpx_client(monkeypatch, handler)

        result = notify_main(
            message="Build done",
            channel="webhook",
            target="https://hooks.example.com/notify",
        )
        assert result.startswith("Error:")
        assert "500" in result


class TestNotificationToolValidation:
    def test_missing_message_returns_error(self):
        result = notify_main(message="", channel="email", target="ops@example.com")
        assert result.startswith("Error:")
        assert "message" in result

    def test_invalid_channel_returns_error(self):
        result = notify_main(
            message="hi", channel="carrier-pigeon", target="ops@example.com"
        )
        assert result.startswith("Error:")
        assert "channel" in result

    def test_missing_target_returns_error(self):
        result = notify_main(message="hi", channel="email", target="")
        assert result.startswith("Error:")
        assert "target" in result

    def test_message_over_200_chars_is_truncated(self, monkeypatch):
        _mock_public_dns(monkeypatch)
        long_message = "x" * 250
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            captured["payload"] = _json.loads(request.content)
            return httpx.Response(200, json={"ok": True})

        _mock_httpx_client(monkeypatch, handler)

        result = notify_main(
            message=long_message,
            channel="webhook",
            target="https://hooks.example.com/notify",
        )

        assert len(captured["payload"]["message"]) == 200
        assert "truncated to 200 characters" in result
