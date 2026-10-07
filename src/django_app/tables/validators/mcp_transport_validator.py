from urllib.parse import urlparse

from django.core.exceptions import ValidationError

# Lowercase only: fastmcp infers the transport from a case-sensitive prefix, so
# "HTTPS://..." would be treated as a local script path, not a URL.
ALLOWED_TRANSPORT_PREFIXES = ("http://", "https://")
INVALID_TRANSPORT_MESSAGE = "Transport must be an http:// or https:// URL with a host."


def validate_mcp_transport_url(value: str) -> None:
    """Reject any MCP transport that is not an http(s) URL with a host.

    fastmcp treats a filesystem path or a non-URL string as a local script and spawns
    it as a process. Django's URLValidator is not used because it rejects single-label
    hosts such as ``http://mcp-server:8000/sse`` that are normal inside docker networks.
    """
    if not value.startswith(ALLOWED_TRANSPORT_PREFIXES):
        raise ValidationError(INVALID_TRANSPORT_MESSAGE, code="invalid_transport")
    try:
        parsed = urlparse(value)
    except ValueError as exc:
        # urlparse raises on malformed input such as an unclosed IPv6 bracket.
        raise ValidationError(INVALID_TRANSPORT_MESSAGE, code="invalid_transport") from exc
    if not parsed.netloc:
        raise ValidationError(INVALID_TRANSPORT_MESSAGE, code="invalid_transport")
