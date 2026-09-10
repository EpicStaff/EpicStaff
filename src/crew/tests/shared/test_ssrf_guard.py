"""Unit tests for the shared SSRF guard (src.shared.security.ssrf_guard).

DNS resolution is mocked throughout so tests are hermetic and fast.
"""

import socket
from unittest.mock import patch

import pytest

from src.shared.security import SsrfBlockedError, assert_public_url, is_public_url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_getaddrinfo(ip: str):
    """Return a patcher that makes socket.getaddrinfo resolve to a single IP."""
    return patch(
        "src.shared.security.ssrf_guard.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 80))],
    )


def _mock_getaddrinfo_multi(*ips: str):
    """Return a patcher that resolves to multiple IPs (e.g. for dual-stack hosts)."""
    records = [
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 80)) for ip in ips
    ]
    return patch(
        "src.shared.security.ssrf_guard.socket.getaddrinfo",
        return_value=records,
    )


def _mock_unresolvable():
    """Return a patcher that simulates a DNS failure."""
    return patch(
        "src.shared.security.ssrf_guard.socket.getaddrinfo",
        side_effect=socket.gaierror("Name or service not known"),
    )


# ---------------------------------------------------------------------------
# Blocked: internal / non-routable addresses
# ---------------------------------------------------------------------------


def test_blocks_cloud_metadata_endpoint():
    """169.254.169.254 is the AWS/GCP/Azure metadata service — must be blocked."""
    with _mock_getaddrinfo("169.254.169.254"):
        with pytest.raises(SsrfBlockedError):
            assert_public_url("http://169.254.169.254/latest/meta-data/")


def test_blocks_hostname_resolving_to_redis_private_ip():
    """A hostname like 'redis' that resolves to a RFC-1918 address must be blocked."""
    with _mock_getaddrinfo("10.0.0.5"):
        with pytest.raises(SsrfBlockedError):
            assert_public_url("http://redis:6379")


def test_blocks_localhost():
    with _mock_getaddrinfo("127.0.0.1"):
        with pytest.raises(SsrfBlockedError):
            assert_public_url("http://localhost")


def test_blocks_private_range_10_x():
    with _mock_getaddrinfo("10.0.0.5"):
        with pytest.raises(SsrfBlockedError):
            assert_public_url("http://10.0.0.5")


def test_blocks_private_range_192_168():
    with _mock_getaddrinfo("192.168.1.1"):
        with pytest.raises(SsrfBlockedError):
            assert_public_url("http://192.168.1.1")


def test_blocks_private_range_172_16():
    with _mock_getaddrinfo("172.16.0.1"):
        with pytest.raises(SsrfBlockedError):
            assert_public_url("http://internal-mcp.company.internal")


def test_blocks_link_local_ip_directly():
    """Direct link-local IP in the URL — blocked even if DNS isn't queried
    (the hostname path resolves it via getaddrinfo, which we mock to return itself)."""
    with _mock_getaddrinfo("169.254.1.1"):
        with pytest.raises(SsrfBlockedError):
            assert_public_url("http://169.254.1.1/mcp")


def test_blocks_loopback_ipv6():
    with _mock_getaddrinfo("::1"):
        with pytest.raises(SsrfBlockedError):
            assert_public_url("http://[::1]/mcp")


def test_blocks_if_any_resolved_ip_is_private():
    """If a hostname resolves to both public and private IPs, it must be blocked."""
    with _mock_getaddrinfo_multi("93.184.216.34", "10.0.0.1"):
        with pytest.raises(SsrfBlockedError):
            assert_public_url("http://dual-stack.example.com/mcp")


# ---------------------------------------------------------------------------
# Blocked: scheme violations
# ---------------------------------------------------------------------------


def test_blocks_file_scheme():
    with pytest.raises(SsrfBlockedError, match="scheme"):
        assert_public_url("file:///etc/passwd")


def test_blocks_gopher_scheme():
    with pytest.raises(SsrfBlockedError, match="scheme"):
        assert_public_url("gopher://internal.host/")


def test_blocks_schemeless_string():
    with pytest.raises(SsrfBlockedError):
        assert_public_url("internal-host/path")


def test_blocks_empty_url():
    with pytest.raises(SsrfBlockedError):
        assert_public_url("")


# ---------------------------------------------------------------------------
# Blocked: unresolvable host
# ---------------------------------------------------------------------------


def test_blocks_unresolvable_host():
    with _mock_unresolvable():
        with pytest.raises(SsrfBlockedError, match="could not be resolved"):
            assert_public_url("http://this-host-does-not-exist.invalid/mcp")


# ---------------------------------------------------------------------------
# Allowed: valid public URL
# ---------------------------------------------------------------------------


def test_allows_public_https_url():
    """A hostname resolving to a public IP (93.184.216.34 = example.com) is allowed."""
    with _mock_getaddrinfo("93.184.216.34"):
        # Must not raise
        assert_public_url("https://example.com/mcp/sse")


def test_allows_public_http_url():
    with _mock_getaddrinfo("8.8.8.8"):
        assert_public_url("http://mcp.public-vendor.io/sse")


# ---------------------------------------------------------------------------
# is_public_url boolean wrapper
# ---------------------------------------------------------------------------


def test_is_public_url_returns_true_for_public():
    with _mock_getaddrinfo("93.184.216.34"):
        assert is_public_url("https://example.com/mcp") is True


def test_is_public_url_returns_false_for_private():
    with _mock_getaddrinfo("10.0.0.1"):
        assert is_public_url("http://internal.example.com") is False


def test_is_public_url_returns_false_for_bad_scheme():
    assert is_public_url("file:///etc/passwd") is False
