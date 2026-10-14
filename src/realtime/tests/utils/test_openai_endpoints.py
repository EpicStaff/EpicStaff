import pytest

from utils.openai_endpoints import derive_chat_http_url, derive_realtime_ws_url


@pytest.mark.parametrize(
    ("base_url", "ws_url", "http_url"),
    [
        (None, "wss://api.openai.com/v1/realtime", None),
        ("", "wss://api.openai.com/v1/realtime", None),
        ("https://my-proxy.internal", "wss://my-proxy.internal/v1/realtime", "https://my-proxy.internal/v1"),
        ("https://my-proxy.internal/", "wss://my-proxy.internal/v1/realtime", "https://my-proxy.internal/v1"),
        ("http://localhost:8080", "ws://localhost:8080/v1/realtime", "http://localhost:8080/v1"),
    ],
    ids=["none", "empty", "https", "trailing-slash", "http"],
)
def test_org_base_url_becomes_the_realtime_and_chat_endpoints(base_url, ws_url, http_url):
    assert (derive_realtime_ws_url(base_url), derive_chat_http_url(base_url)) == (ws_url, http_url)


@pytest.mark.parametrize("base_url", ["my-proxy.internal", "ftp://my-proxy.internal", "https://"])
@pytest.mark.parametrize("derive", [derive_realtime_ws_url, derive_chat_http_url], ids=["realtime", "chat"])
def test_a_base_url_without_http_scheme_and_host_is_rejected(derive, base_url):
    with pytest.raises(ValueError):
        derive(base_url)
