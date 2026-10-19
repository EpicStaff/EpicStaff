import ipaddress

from litestar import Request
from litestar.connection import ASGIConnection


def resolve_client_ip(peer: str | None, forwarded_for: str | None, trusted) -> str:
    """The last X-Forwarded-For entry when the peer is a trusted proxy (nginx appends the real client last)."""
    if not peer:
        return "unknown"
    try:
        peer_address = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if forwarded_for and any(peer_address in network for network in trusted):
        last = forwarded_for.split(",")[-1].strip()
        if last:
            return last
    return peer


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else None
    return resolve_client_ip(
        peer, request.headers.get("x-forwarded-for"), request.app.state.settings.trusted_networks
    )


def bearer_token(request: ASGIConnection) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def last_event_id(request: Request) -> int | None:
    raw = request.headers.get("last-event-id")
    return int(raw) if raw and raw.isascii() and raw.isdigit() else None


def origin(request: Request) -> str | None:
    return request.headers.get("origin")
