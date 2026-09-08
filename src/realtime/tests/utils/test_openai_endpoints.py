import pytest

from utils.openai_endpoints import derive_chat_http_url, derive_realtime_ws_url


class TestDeriveRealtimeWsUrl:
    def test_none_falls_back_to_hardcoded_default(self):
        assert derive_realtime_ws_url(None) == "wss://api.openai.com/v1/realtime"

    def test_empty_string_falls_back_to_hardcoded_default(self):
        assert derive_realtime_ws_url("") == "wss://api.openai.com/v1/realtime"

    def test_https_scheme_swapped_to_wss(self):
        assert (
            derive_realtime_ws_url("https://my-proxy.internal")
            == "wss://my-proxy.internal/v1/realtime"
        )

    def test_http_scheme_swapped_to_ws(self):
        assert (
            derive_realtime_ws_url("http://localhost:8080")
            == "ws://localhost:8080/v1/realtime"
        )

    def test_trailing_slash_stripped(self):
        assert (
            derive_realtime_ws_url("https://my-proxy.internal/")
            == "wss://my-proxy.internal/v1/realtime"
        )

    def test_missing_scheme_raises(self):
        with pytest.raises(ValueError):
            derive_realtime_ws_url("my-proxy.internal")


class TestDeriveChatHttpUrl:
    def test_none_returns_none(self):
        assert derive_chat_http_url(None) is None

    def test_empty_string_returns_none(self):
        assert derive_chat_http_url("") is None

    def test_appends_v1_and_strips_trailing_slash(self):
        assert (
            derive_chat_http_url("https://my-proxy.internal/")
            == "https://my-proxy.internal/v1"
        )

    def test_keeps_http_scheme_as_is(self):
        assert derive_chat_http_url("http://localhost:8080") == "http://localhost:8080/v1"
