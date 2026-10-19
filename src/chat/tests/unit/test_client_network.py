import pytest
from common.utils import client_network


@pytest.mark.parametrize("address", ["1.2.3.4", "127.0.0.1", "unknown", "testclient"])
def test_ipv4_and_non_addresses_are_unchanged(address):
    assert client_network(address) == address


def test_ipv6_addresses_in_one_slash_64_share_a_network():
    assert client_network("2001:db8:1:2::1") == client_network("2001:db8:1:2:ffff:ffff:ffff:ffff") == "2001:db8:1:2::/64"


def test_ipv6_addresses_in_different_slash_64s_do_not():
    assert client_network("2001:db8:1:2::1") != client_network("2001:db8:1:3::1")


def test_zone_id_and_ipv4_mapped_forms():
    assert client_network("fe80::1%eth0") == "fe80::/64"
    assert client_network("::ffff:1.2.3.4") == "1.2.3.4"
