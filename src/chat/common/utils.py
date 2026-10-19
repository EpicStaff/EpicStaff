import ipaddress
import uuid
from datetime import UTC, date, datetime

from uuid_utils.compat import uuid7

__all__ = ["INTEGER_COLUMN_MAX", "client_network", "new_id", "utc_today", "utcnow"]

# Postgres INTEGER: the budget columns cannot hold more.
INTEGER_COLUMN_MAX = 2_147_483_647


def utcnow() -> datetime:
    return datetime.now(UTC)


def utc_today() -> date:
    return utcnow().date()


def new_id() -> uuid.UUID:
    """A UUIDv7: time-ordered, safe to expose, reveals no counts."""
    return uuid7()


def client_network(client_ip: str) -> str:
    """The key per-IP limits count under: an IPv6 client's /64, anything else as given.

    One IPv6 host usually holds a whole /64, so a per-address limit would be no limit.
    An IPv4-mapped IPv6 address counts as its IPv4 address.
    """
    try:
        address = ipaddress.ip_address(client_ip)
    except ValueError:
        return client_ip
    if address.version == 4:
        return client_ip
    if address.ipv4_mapped:
        return str(address.ipv4_mapped)
    # Through the int, so a zone id ("%eth0") is dropped with the host bits.
    return f"{ipaddress.IPv6Address(int(address) >> 64 << 64)}/64"
