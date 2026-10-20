import ipaddress

from presentation.rest.request_context import resolve_client_ip

PRIVATE = [ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12")]


def test_forwarded_for_last_entry_from_trusted_proxy():
    assert resolve_client_ip(peer="172.18.0.5", forwarded_for="1.2.3.4, 5.6.7.8", trusted=PRIVATE) == "5.6.7.8"


def test_forwarded_for_ignored_from_untrusted_peer():
    assert resolve_client_ip(peer="8.8.8.8", forwarded_for="1.2.3.4", trusted=PRIVATE) == "8.8.8.8"


def test_no_header_and_non_ip_peer():
    assert resolve_client_ip(peer="172.18.0.5", forwarded_for=None, trusted=PRIVATE) == "172.18.0.5"
    assert resolve_client_ip(peer="testclient", forwarded_for="1.2.3.4", trusted=PRIVATE) == "testclient"
    assert resolve_client_ip(peer=None, forwarded_for=None, trusted=PRIVATE) == "unknown"
