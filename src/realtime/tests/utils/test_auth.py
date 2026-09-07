from unittest.mock import MagicMock

import pytest

import utils.auth as auth_module


@pytest.fixture(autouse=True)
def _reset_validation_cache():
    """validate_api_key() memoizes success in a module-level flag; reset between tests."""
    auth_module._api_key_validated = False
    yield
    auth_module._api_key_validated = False


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {"active": True}
    return response


def test_validate_api_key_overrides_host_header(monkeypatch):
    """DJANGO_AUTH_URL points at the Docker Compose service name `django_app`,
    which contains an underscore and fails Django's host_validation_re when used
    verbatim as the Host header. The Host header must be pinned to a value
    (e.g. "localhost") that is both regex-valid and present in ALLOWED_HOSTS,
    while the request still connects to the real service via the URL authority.
    """
    captured = {}

    def fake_get(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        return _mock_response()

    monkeypatch.setattr(auth_module.httpx, "get", fake_get)

    result = auth_module.validate_api_key()

    assert result is True
    assert captured["headers"]["Host"] == "localhost"
    assert "django_app" in captured["url"]


def test_introspect_token_overrides_host_header(monkeypatch):
    monkeypatch.setattr(auth_module, "_api_key_validated", True)

    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        return _mock_response(json_data={"active": True, "sub": "user-1"})

    monkeypatch.setattr(auth_module.httpx, "post", fake_post)

    result = auth_module.introspect_token("some-token")

    assert result == {"active": True, "sub": "user-1"}
    assert captured["headers"]["Host"] == "localhost"
    assert "django_app" in captured["url"]
