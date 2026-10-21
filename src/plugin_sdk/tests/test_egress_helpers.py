import pytest

from epicstaff_plugin import egress
from epicstaff_plugin.contracts import runtime
from epicstaff_plugin.contracts.runtime import HTTPS_PROXY_ENVIRONMENT_VARIABLE
from epicstaff_plugin.egress import EgressProxyUnavailable, proxy_url

PROXY = "http://weather:proxy-password@plugins_egress:3128"


def test_the_environment_names_are_the_ones_the_node_sets():
    assert runtime.PROXY_ENVIRONMENT_VARIABLES == ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
    assert runtime.NO_PROXY_ENVIRONMENT_VARIABLES == ("NO_PROXY", "no_proxy")
    assert runtime.LOOPBACK_NO_PROXY_HOSTS == ("localhost", "127.0.0.1", "::1")
    assert HTTPS_PROXY_ENVIRONMENT_VARIABLE == runtime.PROXY_ENVIRONMENT_VARIABLES[0] == "HTTPS_PROXY"
    # Declared once, in the runtime contract.
    assert egress.HTTPS_PROXY_ENVIRONMENT_VARIABLE is runtime.HTTPS_PROXY_ENVIRONMENT_VARIABLE


def test_proxy_url_reads_https_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", PROXY)

    assert proxy_url() == PROXY


@pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
def test_proxy_url_off_the_node_raises(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("HTTPS_PROXY", raising=False)
    else:
        monkeypatch.setenv("HTTPS_PROXY", value)

    with pytest.raises(EgressProxyUnavailable, match="HTTPS_PROXY is not set"):
        proxy_url()
