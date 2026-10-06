"""Per-uid egress firewall that keeps user code off private networks.

`sandbox-network` is an ordinary Docker bridge, so without this an execution
can reach the Docker host (on Docker Desktop even services bound to the host's
127.0.0.1, via host.docker.internal), the LAN, cloud metadata
(169.254.169.254) and every container on sandbox-network, Redis included. One
sandbox serves every organization on the instance, which makes that both a
host and a cross-tenant exposure. Dropping `extra_hosts` does not close it:
Docker Desktop resolves host.docker.internal regardless, and on Linux the
bridge gateway stays reachable.

The rules match the socket owner's uid (`-m owner --uid-owner`), so only the
dropped-privilege user-code child is filtered: the root supervisor's Redis
connection and pip's package downloads are unaffected, and user code keeps
plain internet access. Only private, link-local, shared, reserved and
multicast destinations are rejected, with carve-outs for DNS and storage.

Applied once at startup via `iptables-restore`. Needs the iptables binary
(Dockerfile.sandbox), CAP_NET_ADMIN, and a kernel with the xt_owner match.
`ExecuteCodeHandler` refuses to execute when the firewall is required but
`is_active()` is False.
"""

import ipaddress
import socket
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import settings
from utils.logger import logger

RESOLV_CONF_PATH = Path("/etc/resolv.conf")
# Lists the netns's IPv6 addresses; absent when the kernel has IPv6 disabled,
# in which case there is no IPv6 traffic to filter and ip6tables may not work.
_IF_INET6_PATH = Path("/proc/net/if_inet6")

_CHAIN = "SANDBOX_EGRESS"

# 127.0.0.0/8 is deliberately absent: it is the container's own loopback and
# hosts Docker's embedded DNS (127.0.0.11), which the nat table DNATs to a
# random port, so no port-based carve-out could keep it open.
# NOTE: these are the standard private/reserved ranges. A Docker daemon whose
# default-address-pools (or a compose ipam subnet) uses public-looking
# addresses puts sandbox-network outside them, and Redis becomes reachable again.
BLOCKED_IPV4_RANGES: tuple[str, ...] = (
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "224.0.0.0/4",
    "240.0.0.0/4",
)


class EgressFirewallUnavailableError(Exception):
    """The firewall could not be installed (no iptables, no CAP_NET_ADMIN, no xt_owner)."""


@dataclass(frozen=True)
class EgressCarveOuts:
    """Private destinations user code may still reach through the firewall."""

    nameservers: tuple[str, ...]
    storage_endpoints: tuple[tuple[str, int], ...]


_active_carve_outs: EgressCarveOuts | None = None


def is_active() -> bool:
    """Whether `apply()` has installed the firewall in this process."""
    return _active_carve_outs is not None


def active_carve_outs() -> EgressCarveOuts | None:
    """The carve-outs of the installed firewall, or None when it is not installed."""
    return _active_carve_outs


def build_ipv4_rules(
    *,
    uid: int,
    nameservers: Iterable[str],
    storage_endpoints: Iterable[tuple[str, int]],
) -> str:
    """Build `iptables-restore` input rejecting `uid`'s traffic to private IPv4 ranges.

    The ACCEPT carve-outs precede the REJECTs because the chain is first-match.
    The input replaces the whole `filter` table (no `--noflush`), so applying it
    twice yields the same ruleset. That is safe because Docker only writes to
    the container netns's `nat` table, which this input does not touch.
    """
    lines = [
        "*filter",
        f":{_CHAIN} - [0:0]",
        f"-A OUTPUT -m owner --uid-owner {uid} -j {_CHAIN}",
    ]
    for nameserver in nameservers:
        for protocol in ("udp", "tcp"):
            lines.append(f"-A {_CHAIN} -d {nameserver}/32 -p {protocol} --dport 53 -j ACCEPT")
    for storage_ip, storage_port in storage_endpoints:
        lines.append(f"-A {_CHAIN} -d {storage_ip}/32 -p tcp --dport {storage_port} -j ACCEPT")
    # admin-prohibited surfaces as "No route to host" rather than the default
    # "Connection refused", so a blocked LAN database doesn't look like it is down.
    lines.extend(
        f"-A {_CHAIN} -d {blocked_range} -j REJECT --reject-with icmp-admin-prohibited"
        for blocked_range in BLOCKED_IPV4_RANGES
    )
    lines.append("COMMIT")
    return "\n".join(lines) + "\n"


def build_ipv6_rules(*, uid: int) -> str:
    """Build `ip6tables-restore` input rejecting all of `uid`'s non-loopback IPv6.

    Docker networks have no IPv6 egress by default and clients fall back to
    IPv4, so rejecting all of it loses no internet access while closing
    link-local and ULA paths to the host and other containers.
    """
    return f"*filter\n-A OUTPUT -m owner --uid-owner {uid} ! -o lo -j REJECT --reject-with icmp6-adm-prohibited\nCOMMIT\n"


def read_ipv4_nameservers(resolv_conf: Path) -> tuple[str, ...]:
    """Return the IPv4 `nameserver` entries of `resolv_conf`, or () if it is missing.

    Needed because the resolver is not always Docker's 127.0.0.11: under podman
    or the default bridge it is a private address (e.g. 10.89.0.1) that the
    REJECT ranges would otherwise cut off, breaking DNS for user code.
    """
    try:
        content = resolv_conf.read_text()
    except FileNotFoundError:
        return ()

    nameservers: list[str] = []
    for line in content.splitlines():
        fields = line.split()
        if len(fields) < 2 or fields[0] != "nameserver":
            continue
        try:
            address = ipaddress.ip_address(fields[1])
        except ValueError:
            continue
        if address.version == 4:
            nameservers.append(str(address))
    return tuple(nameservers)


def _resolve_storage_endpoints() -> tuple[tuple[str, int], ...]:
    # NOTE: the storage IP is pinned at startup. If the storage container is
    # recreated with a new IP, user-code storage calls fail closed until the
    # sandbox restarts; re-resolve per execution if that becomes a problem.
    storage_port = int(settings.STORAGE_PORT)
    try:
        address_infos = socket.getaddrinfo(
            settings.STORAGE_HOST, storage_port, socket.AF_INET, socket.SOCK_STREAM
        )
    except socket.gaierror as error:
        logger.warning(
            "Could not resolve storage host {} for the egress firewall carve-out: {}. "
            "Storage-enabled executions will be unable to reach storage.",
            settings.STORAGE_HOST,
            error,
        )
        return ()
    return tuple(sorted({(info[4][0], storage_port) for info in address_infos}))


def _restore(command: str, rules: str) -> None:
    try:
        subprocess.run([command], input=rules, check=True, capture_output=True, text=True)
    except OSError as error:
        raise EgressFirewallUnavailableError(f"{command} could not be run: {error}") from error
    except subprocess.CalledProcessError as error:
        raise EgressFirewallUnavailableError(
            f"{command} exited with {error.returncode}: {error.stderr.strip()}"
        ) from error


def apply(uid: int) -> None:
    """Install the egress firewall for `uid` and mark it active.

    Runs a blocking subprocess: it is called once from startup, before the
    event loop serves any task, so there is nothing for it to stall.

    Raises:
        EgressFirewallUnavailableError: iptables is missing, the container lacks
            CAP_NET_ADMIN, or the kernel lacks the owner match. The firewall is
            then not marked active.
    """
    global _active_carve_outs

    carve_outs = EgressCarveOuts(
        nameservers=read_ipv4_nameservers(RESOLV_CONF_PATH),
        storage_endpoints=_resolve_storage_endpoints(),
    )
    _restore(
        "iptables-restore",
        build_ipv4_rules(
            uid=uid,
            nameservers=carve_outs.nameservers,
            storage_endpoints=carve_outs.storage_endpoints,
        ),
    )
    if _IF_INET6_PATH.exists():
        _restore("ip6tables-restore", build_ipv6_rules(uid=uid))
    _active_carve_outs = carve_outs
