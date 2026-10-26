#!/usr/bin/python3 -I
"""Squid's external ACL helper for plugins_egress: may this plugin open a tunnel to this host?

Squid starts it as `plugin_host_acl <hosts.json>` and writes one request per line,
`<user> <host> -`: the proxy user (a plugin's identifier), the CONNECT host and `-` for the
empty `%DATA`, the first two URL-escaped. It answers each line with `OK` or `ERR`. A line of any
other shape, and any problem with the policy file, is answered `ERR`. The helper never exits on
bad input: Squid stops altogether when its helpers keep dying.

The policy file is `{"<identifier>": ["host", "*.domain", ...]}`, written by the plugin node. An
exact entry allows that host. `*.domain` allows every subdomain of `domain` at any depth, never
`domain` itself and never a name that merely ends in the same letters. Hosts and entries are
compared lower-cased, without IPv6 brackets or a trailing dot. The file is read again whenever its
inode, modification time or size changes, so the node's atomic replace applies to the next
request Squid does not answer from its cache. A file that is missing, unreadable or of any other
shape refuses everyone.

Only counts are logged (to stderr, Squid's cache log): never a host, a user or a list.
Standard library only.
"""

import json
import os
import sys
from urllib.parse import unquote

EMPTY_DATA_FIELD = b"-"
WILDCARD_PREFIX = "*."


def log(message: str) -> None:
    sys.stderr.write(f"plugin_host_acl: {message}\n")
    sys.stderr.flush()


class InvalidPolicyError(Exception):
    """The policy file is not an object of lists of strings; the message says how."""


def normalize_host(host: str) -> str:
    """Lower-cased, without the brackets of an IPv6 literal or the trailing dot of a full name."""
    host = host.lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host.removesuffix(".")


class PluginHosts:
    """One plugin's list: exact hosts, and the `.domain` suffixes of its `*.domain` entries."""

    def __init__(self, entries: list[str]):
        normalized = [normalize_host(entry) for entry in entries]
        self.exact = frozenset(
            entry for entry in normalized if not entry.startswith(WILDCARD_PREFIX)
        )
        self.suffixes = tuple(
            entry[1:]
            for entry in normalized
            if entry.startswith(WILDCARD_PREFIX) and len(entry) > 2
        )

    def allows(self, host: str) -> bool:
        # An empty label (a leading dot, two dots in a row) is no name any entry stands for.
        if not host or "" in host.split("."):
            return False
        return host in self.exact or any(host.endswith(suffix) for suffix in self.suffixes)


class HostPolicy:
    """The policy file, read again whenever its inode, modification time or size changes."""

    def __init__(self, path: str):
        self._path = path
        self._signature: tuple[int, int, int] | None = None
        self._plugins: dict[str, PluginHosts] = {}
        self._readable = True

    def allows(self, user: str, host: str) -> bool:
        self._refresh()
        plugin = self._plugins.get(user)
        return plugin is not None and plugin.allows(host)

    def _refresh(self) -> None:
        try:
            with open(self._path, "rb") as policy_file:
                status = os.fstat(policy_file.fileno())
                signature = (status.st_ino, status.st_mtime_ns, status.st_size)
                if signature == self._signature:
                    return
                content = policy_file.read()
        except OSError as error:
            if self._readable:
                log(f"policy file unreadable ({type(error).__name__}); refusing everyone")
            self._readable, self._signature, self._plugins = False, None, {}
            return
        self._readable, self._signature = True, signature
        try:
            self._plugins = parse_policy(content)
        except InvalidPolicyError as error:
            log(f"policy file invalid ({error}); refusing everyone")
            self._plugins = {}
            return
        log(
            f"policy loaded: {len(self._plugins)} plugins, "
            f"{sum(len(plugin.exact) + len(plugin.suffixes) for plugin in self._plugins.values())} hosts"
        )


def parse_policy(content: bytes) -> dict[str, PluginHosts]:
    """The plugins of a policy file; anything but an object of lists of strings is refused whole."""
    try:
        policy = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InvalidPolicyError("not JSON") from None
    if not isinstance(policy, dict):
        raise InvalidPolicyError("not an object")
    for entries in policy.values():
        if not isinstance(entries, list) or not all(isinstance(entry, str) for entry in entries):
            raise InvalidPolicyError("a value is not a list of strings")
    return {identifier: PluginHosts(entries) for identifier, entries in policy.items()}


def answer(policy: HostPolicy, line: bytes) -> str:
    fields = line.split()
    if len(fields) != 3 or fields[2] != EMPTY_DATA_FIELD:
        return "ERR"
    try:
        user = unquote(fields[0].decode("ascii"), errors="strict")
        host = normalize_host(unquote(fields[1].decode("ascii"), errors="strict"))
    except UnicodeDecodeError:
        return "ERR"
    return "OK" if policy.allows(user, host) else "ERR"


def main() -> int:
    if len(sys.argv) != 2:
        log("usage: plugin_host_acl <hosts.json>")
        return 2
    policy = HostPolicy(sys.argv[1])
    for line in sys.stdin.buffer:
        try:
            reply = answer(policy, line)
        # Any failure is an answer, not an exit: Squid stops when its helpers keep dying.
        except Exception as error:
            log(f"answering ERR after {type(error).__name__}")
            reply = "ERR"
        sys.stdout.write(reply + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
