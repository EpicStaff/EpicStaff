"""The egress proxy's policy, written by the agent into the volume plugins_egress reads.

Two files, in `/var/lib/es_plugins_egress/policy` here and `/etc/squid/policy` in plugins_egress:

- `passwords`: `<identifier>:<bcrypt $2b$ hash>` lines, sorted, one for each plugin whose process
  the node runs. Squid checks the proxy credentials against it.
- `hosts.json`: `{"<identifier>": [host, …]}`, keys sorted, one for each placement of the desired
  state (an empty list included), hosts in manifest order. Squid's host helper allows a CONNECT
  only to a host its user's list names.

A plugin's proxy password lives only in this agent's memory and in its process's environment.
It is issued when the controller first starts the process, kept while the process is restarted,
and removed once the process is stopped for good. `start` empties both files, so a password never
outlives the agent that issued it.

Both files are mode 0644 and replaced atomically (temporary file, fsync, rename, fsync of the
directory), so the proxy never reads part of one. A new password works within about a second; a
removed password or host stops working within about 30 s, the proxy's cache times. Squid's
password helper reads its file again only when the file's modification time, in whole seconds,
changes, so each new password file is dated at least a second after the one it replaces.

No password, hash or host list is ever logged; `plugins.egress.policy_written` gives counts.
"""

import asyncio
import json
import os
import secrets
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import bcrypt
from loguru import logger

from es_plugins.descriptors import write_all

PASSWORDS_FILE_NAME = "passwords"
HOSTS_FILE_NAME = "hosts.json"
# Where plugins reach the proxy, on plugins-network.
EGRESS_PROXY_HOST = "plugins_egress"
EGRESS_PROXY_PORT = 3128
EGRESS_PROXY_ADDRESS = f"{EGRESS_PROXY_HOST}:{EGRESS_PROXY_PORT}"
# The passwords are 192-bit random tokens, which no cost factor makes harder to guess. The proxy
# checks a hash for every request it is sent, so a higher cost would only let one plugin's flood
# of wrong passwords slow everyone's outbound access. 4 is bcrypt's lowest cost.
BCRYPT_ROUNDS = 4
# 32 URL-safe characters: the password sits in the userinfo of the plugin's proxy URL.
PASSWORD_BYTES = 24
POLICY_FILE_MODE = 0o644


class EgressPolicyError(Exception):
    """The policy directory is missing or cannot be written; the message names it."""


@dataclass(frozen=True)
class _ProxyPassword:
    password: str = field(repr=False)
    bcrypt_hash: str = field(repr=False)


class EgressPolicyWriter:
    def __init__(self, directory: Path):
        self._directory = directory
        self._passwords: dict[str, _ProxyPassword] = {}
        self._hosts: dict[str, list[str]] = {}
        self._hosts_text: str | None = None
        # One write at a time; each writes the whole current state, so the last one wins.
        self._write_lock = asyncio.Lock()

    async def start(self) -> None:
        """Write an empty password file and `{}`, before any plugin starts.

        Raises:
            EgressPolicyError: The directory is missing or cannot be written.
        """
        self._passwords.clear()
        await self.write_passwords()
        await self.write_hosts({})

    async def write_hosts(self, hosts: Mapping[str, Sequence[str]]) -> None:
        """Make `hosts.json` list `hosts` (identifier -> its hosts); unchanged, nothing is written.

        Raises:
            EgressPolicyError: The file could not be replaced.
        """
        async with self._write_lock:
            await self._write_hosts_locked({key: list(value) for key, value in hosts.items()})
        self._log_written()

    async def issue_password(self, identifier: str) -> str:
        """Return the plugin's active proxy password, issuing one if it has none.

        A new one is hashed and written before this returns, so the process can use it at once.

        Raises:
            EgressPolicyError: The password file could not be replaced.
        """
        if (active := self._passwords.get(identifier)) is not None:
            return active.password
        password = secrets.token_urlsafe(PASSWORD_BYTES)
        hashed = await asyncio.to_thread(_bcrypt_hash, password)
        # Another call for the same plugin may have issued one while this one was hashing.
        if (active := self._passwords.get(identifier)) is not None:
            return active.password
        issued = _ProxyPassword(password, hashed)
        self._passwords[identifier] = issued
        try:
            await self.write_passwords()
        except EgressPolicyError:
            # Not in the file, so not usable: a later start issues a new one.
            if self._passwords.get(identifier) is issued:
                del self._passwords[identifier]
            raise
        return password

    def forget_password(self, identifier: str) -> bool:
        """Drop the plugin's password from memory at once; return whether it had one.

        The file follows with the next `write_passwords`. A later `issue_password` issues a new
        password, never the forgotten one.
        """
        return self._passwords.pop(identifier, None) is not None

    async def remove_password(self, identifier: str) -> None:
        """The plugin's process is stopped for good: its password stops working.

        Raises:
            EgressPolicyError: The password file could not be replaced.
        """
        if self.forget_password(identifier):
            await self.write_passwords()

    async def remove_plugin(self, identifier: str) -> None:
        """The plugin is being removed from the node: drop its password and its host list.

        Doing it again changes nothing. `Reconciler.apply` already leaves a removed plugin out of
        `hosts.json`; this also covers a removal the agent resumes after a restart.

        Raises:
            EgressPolicyError: A policy file could not be replaced.
        """
        await self.remove_password(identifier)
        async with self._write_lock:
            # Taken from the current list under the lock, so a newer list is never overwritten.
            if identifier in self._hosts:
                await self._write_hosts_locked(
                    {key: value for key, value in self._hosts.items() if key != identifier}
                )
        self._log_written()

    async def write_passwords(self) -> None:
        """Write the password file as the passwords in memory are now.

        Raises:
            EgressPolicyError: The file could not be replaced.
        """
        async with self._write_lock:
            lines = "".join(
                f"{identifier}:{self._passwords[identifier].bcrypt_hash}\n"
                for identifier in sorted(self._passwords)
            )
            await self._replace(PASSWORDS_FILE_NAME, lines, dated_after_previous=True)
        self._log_written()

    async def _write_hosts_locked(self, hosts: dict[str, list[str]]) -> None:
        text = json.dumps(hosts, sort_keys=True, indent=2)
        if text == self._hosts_text:
            return
        await self._replace(HOSTS_FILE_NAME, text + "\n")
        self._hosts = hosts
        self._hosts_text = text

    async def _replace(self, name: str, text: str, *, dated_after_previous: bool = False) -> None:
        try:
            await asyncio.to_thread(
                replace_atomically,
                self._directory,
                name,
                text.encode(),
                dated_after_previous=dated_after_previous,
            )
        except OSError as error:
            raise EgressPolicyError(
                f"the egress policy file {self._directory / name} cannot be written: {error}"
            ) from None

    def _log_written(self) -> None:
        logger.debug(
            "plugins.egress.policy_written users={} hosts={}",
            len(self._passwords),
            sum(len(hosts) for hosts in self._hosts.values()),
        )


def replace_atomically(
    directory: Path, name: str, content: bytes, *, dated_after_previous: bool = False
) -> None:
    """Replace `directory/name` with `content` (mode 0644) so no reader ever sees part of it.

    With `dated_after_previous`, the new file's modification time is a whole second after the
    file it replaces (or now, if that is later), for a reader that reloads only when the whole
    seconds change.
    """
    directory_descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        temporary_name = f".{name}.{secrets.token_hex(8)}"
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            POLICY_FILE_MODE,
            dir_fd=directory_descriptor,
        )
        try:
            write_all(descriptor, content)
            os.fchmod(descriptor, POLICY_FILE_MODE)
            if dated_after_previous:
                modified = _whole_second_after(directory_descriptor, name)
                os.utime(descriptor, (modified, modified))
            os.fsync(descriptor)
        except BaseException:
            os.unlink(temporary_name, dir_fd=directory_descriptor)
            raise
        finally:
            os.close(descriptor)
        try:
            os.replace(
                temporary_name,
                name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
            )
        except BaseException:
            os.unlink(temporary_name, dir_fd=directory_descriptor)
            raise
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _whole_second_after(directory_descriptor: int, name: str) -> int:
    try:
        previous = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False).st_mtime
    except FileNotFoundError:
        return int(time.time())
    return max(int(time.time()), int(previous) + 1)


def _bcrypt_hash(password: str) -> str:
    return bcrypt.hashpw(
        password.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS, prefix=b"2b")
    ).decode()
