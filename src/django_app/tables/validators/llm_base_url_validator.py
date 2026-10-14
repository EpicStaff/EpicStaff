import ipaddress
import socket
from urllib.parse import urlparse

from rest_framework import serializers

# Cloud-metadata destinations an SSRF would target. 169.254.0.0/16 is IPv4
# link-local, which covers the common 169.254.169.254 metadata address;
# 168.63.129.16 is Azure's WireServer, a public-looking address no private range
# covers. Private ranges other than these (10.0.0.0/8, 192.168.0.0/16, ...) are
# intentionally allowed: pointing an LLM/embedding/realtime config at a
# self-hosted Ollama or vLLM on the LAN is a supported use.
_LINK_LOCAL_RANGE = ipaddress.ip_network("169.254.0.0/16")
_AZURE_WIRESERVER = ipaddress.ip_address("168.63.129.16")

_BLOCKED_MESSAGE = (
    "base_url must not point at a cloud metadata endpoint "
    "(link-local 169.254.0.0/16 or Azure WireServer 168.63.129.16)."
)


def _ipv4_from_host(host: str) -> ipaddress.IPv4Address | None:
    """Return the IPv4 address a resolver would derive from host, or None.

    A literal IPv4 host blocks only after it is canonicalized, because the
    outbound client (libc getaddrinfo via httpx/litellm) resolves far more than
    dotted-decimal: a decimal integer (``2852039166``), hex (``0xa9fea9fe``),
    octal (``0251.0376.0251.0376``) and partial forms all reach 169.254.169.254,
    and an IPv4-mapped IPv6 literal (``::ffff:169.254.169.254``) does too. A
    non-mapped IPv6 literal and a real hostname return None -- a hostname is not
    resolved here by design, so DNS rebinding stays out of scope.
    """
    try:
        parsed = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if isinstance(parsed, ipaddress.IPv6Address):
            # ipv4_mapped is the embedded IPv4 for ::ffff:a.b.c.d, else None.
            return parsed.ipv4_mapped
        return parsed

    # Non-canonical IPv4 numeric forms (decimal/hex/octal/partial) that
    # inet_aton decodes the same way the outbound resolver will. A real
    # hostname raises OSError here and falls through to allowed.
    try:
        packed = socket.inet_aton(host)
    except OSError:
        return None
    return ipaddress.IPv4Address(packed)


def validate_llm_base_url(value: str | None) -> None:
    """Reject a base_url whose host resolves to a cloud-metadata IPv4 address.

    Only metadata/link-local IPv4 destinations are blocked -- 169.254.0.0/16 and
    the Azure WireServer 168.63.129.16 -- so a backend LLM, embedding or realtime
    call cannot be aimed at instance credentials, while private LAN ranges stay
    allowed for self-hosted Ollama/vLLM. The host is canonicalized first, so the
    decimal/hex/octal/partial IPv4 encodings and IPv4-mapped IPv6 literals that
    the outbound client would still resolve to a metadata address are caught. A
    plain hostname is left as-is -- resolving it here would not stop DNS
    rebinding, which is out of scope for this validator.

    Raises:
        serializers.ValidationError: The URL host is a metadata/link-local IP.
    """
    if not value:
        return

    # Prepend "//" when there is no scheme so urlparse puts a bare
    # "169.254.169.254:8000" in netloc rather than path, where it has no host.
    parsed = urlparse(value if "://" in value else f"//{value}")
    host = parsed.hostname
    if not host:
        return

    address = _ipv4_from_host(host)
    if address is None:
        return

    if address == _AZURE_WIRESERVER or address in _LINK_LOCAL_RANGE:
        raise serializers.ValidationError(_BLOCKED_MESSAGE)
