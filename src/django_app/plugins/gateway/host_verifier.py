"""Whether a plugin's host is served by this EpicStaff, proved over the network.

A name fits the plugin template whatever DNS says about it. With a flat template
(`{id}-app.example.com`) the plugins share the organization's zone, where a record of its own
(`crm-app.example.com` to another server or a SaaS) beats the wildcard. EpicStaff would then
send a person's login code, and frame its pages, to a server it does not run. Before it trusts
a plugin host it asks that host for the HMAC only this deployment can compute
(`plugins.gateway.host_proof`).

Only a template with an affix is checked. The collision comes from sharing the organization's
zone; an affix-less template (`{id}.plugins.example.com`) gives the plugins a domain of their
own, every name under which is theirs, and is how every server upgraded from a release with
`PLUGINS_BASE_DOMAIN` runs. The check also needs django_app to reach its own public name
(hairpin NAT or split DNS), which some existing deployments cannot: checking affix-less
templates would break them for a risk they do not have. `.localhost` hosts are never checked
either: such names never leave the machine, so no other server can hold them.

What it does not stop: a server that controls such a name and relays the challenge to this
deployment's nginx passes. Whoever controls a DNS name controls that origin; this stops
collisions and foreign hosting, not an active relay.
"""

import asyncio
import concurrent.futures
import hmac
import json
import os
import secrets
import threading
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any

import httpx
from django.core.cache import cache

from plugins.audit import log_plugin_host_unverified
from plugins.development.development_mode import LOCALHOST_SUFFIX
from plugins.exceptions import PluginHostNotServedHereError
from plugins.gateway.host_proof import CHALLENGE_PARAMETER, INSTANCE_PATH, host_proof
from plugins.origins import PluginOrigins

VERIFIED_CACHE_SECONDS = 600
REFUSED_CACHE_SECONDS = 60
INCONCLUSIVE_CACHE_SECONDS = 15
# The whole probe, from connecting to the last byte read (a wall clock, `_probe`). authorize is
# anonymous, so a server at a colliding name must never hold a worker longer than this, however
# slowly it answers.
PROBE_DEADLINE_SECONDS = 3.0
PROBE_STEP_TIMEOUT_SECONDS = 1.0
# This deployment's answer is about 80 bytes; a longer one is not ours.
MAX_ANSWER_BYTES = 1024
# The caller never waits past the deadline, so the lock outlives every probe that holds it; a
# worker that died while probing stops the next probe only this long.
PROBE_LOCK_SECONDS = int(PROBE_DEADLINE_SECONDS) + 3
# Threads that resolve plugin host names for the probes. A name server that never answers holds
# one of them for its own timeout (about 10 s with glibc's defaults); while all are held, new
# probes simply time out at the deadline instead of adding threads.
PROBE_RESOLVER_THREADS = 4
_CACHE_KEY = "plugins:host-verified:{origin}"
_PROBE_LOCK_KEY = "plugins:host-verified:{origin}:probing"


class _ProbeLoop:
    """The event loop every probe of this process runs on, in a daemon thread of its own.

    A sync caller hands it a coroutine and waits at most a deadline; the loop keeps running
    whatever the probe does, so a probe stuck in name resolution (which runs in the loop's
    executor and cannot be cancelled) holds an executor thread, never the caller. Started on
    first use, and again in a process whose id differs from the one that started it: a forked
    worker inherits the loop object but not its thread.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._process_id: int | None = None

    def run(self, coroutine: Coroutine[Any, Any, Any], timeout: float) -> Any:
        """The coroutine's result.

        Raises:
            TimeoutError: It did not finish within `timeout`; it is cancelled.
        """
        future = asyncio.run_coroutine_threadsafe(coroutine, self._running_loop())
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError from None

    def _running_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None or self._process_id != os.getpid():
                loop = asyncio.new_event_loop()
                loop.set_default_executor(
                    concurrent.futures.ThreadPoolExecutor(
                        max_workers=PROBE_RESOLVER_THREADS,
                        thread_name_prefix="plugin-host-probe-resolver",
                    )
                )
                threading.Thread(
                    target=loop.run_forever, name="plugin-host-probe", daemon=True
                ).start()
                self._loop, self._process_id = loop, os.getpid()
            return self._loop


_probe_loop = _ProbeLoop()


@dataclass(frozen=True)
class _Failure:
    """Why a host did not prove itself. `conclusive`: a server answered and it is not this
    deployment; otherwise nothing was learned (unreachable, too slow, overloaded, throttled)."""

    reason: str
    conclusive: bool


class PluginHostVerifier:
    """Proves, and remembers for a while, that a plugin's host reaches this deployment.

    Answers are cached per frame origin. A success lasts `VERIFIED_CACHE_SECONDS`. A conclusive
    failure (another server's answer) lasts `REFUSED_CACHE_SECONDS`, so a fixed DNS record is
    picked up within a minute. An inconclusive one (no answer in time, a 429 or 5xx) lasts
    `INCONCLUSIVE_CACHE_SECONDS`, only to bound how often the host is asked, and never
    replaces a success. One process at a time probes a host: the others use the cached answer
    or, while there is none, treat the host as unverified for that request.
    """

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    def is_served_here(self, identifier: str) -> bool:
        """Whether the host of plugin `identifier` answers with this deployment's proof.

        Always true, without a request, for a template without an affix and for `.localhost`
        plugin hosts (plugin development mode included); see the module docstring for why.
        """
        origins = PluginOrigins()
        template = origins.host_template
        if not template.has_affix or template.parent.endswith(LOCALHOST_SUFFIX):
            return True
        origin = origins.frame_origin(identifier)
        key = _CACHE_KEY.format(origin=origin)
        cached = cache.get(key)
        if cached is not None:
            return cached
        lock_key = _PROBE_LOCK_KEY.format(origin=origin)
        lock_token = secrets.token_hex(16)
        if not cache.add(lock_key, lock_token, PROBE_LOCK_SECONDS):
            # Another process is asking this host now; nothing is written for this request.
            return False
        host = origins.plugin_host(identifier)
        try:
            failure = self._probe(origin, host)
        finally:
            _release(lock_key, lock_token)
        if failure is None:
            cache.set(key, True, VERIFIED_CACHE_SECONDS)
            return True
        log_plugin_host_unverified(host=host, reason=failure.reason)
        if failure.conclusive:
            cache.set(key, False, REFUSED_CACHE_SECONDS)
        else:
            # `add`, not `set`: a success another process cached meanwhile stays.
            cache.add(key, False, INCONCLUSIVE_CACHE_SECONDS)
        return False

    def assert_served_here(self, identifier: str) -> None:
        """Raises:
        PluginHostNotServedHereError: The plugin's host does not answer with this
            deployment's proof.
        """
        if not self.is_served_here(identifier):
            raise PluginHostNotServedHereError(PluginOrigins().plugin_host(identifier))

    def _probe(self, origin: str, host: str) -> _Failure | None:
        """None when `host` proves itself within `PROBE_DEADLINE_SECONDS`, else why not.

        The deadline is a wall clock over the whole exchange, headers included: httpx's own
        timeouts bound each read, not a server that answers one byte at a time, and the name is
        resolved in a thread no cancellation stops. The probe runs on the process's probe loop
        (`_ProbeLoop`) and this caller waits for it only until the deadline.
        """
        challenge = secrets.token_urlsafe(32)
        try:
            answer = _probe_loop.run(self._fetch(origin, challenge), PROBE_DEADLINE_SECONDS)
        except TimeoutError:
            return _Failure("too_slow", conclusive=False)
        except httpx.HTTPError:
            return _Failure("unreachable", conclusive=False)
        if isinstance(answer, _Failure):
            return answer
        try:
            proof = json.loads(answer).get("proof")
        except (ValueError, AttributeError):
            return _Failure("not_a_proof", conclusive=True)
        if not isinstance(proof, str):
            return _Failure("not_a_proof", conclusive=True)
        if not hmac.compare_digest(proof.encode(), host_proof(host, challenge).encode()):
            return _Failure("wrong_proof", conclusive=True)
        return None

    async def _fetch(self, origin: str, challenge: str) -> bytes | _Failure:
        """The answer's body, at most `MAX_ANSWER_BYTES`, or why there is none to judge."""
        # Certificates are not verified on purpose: the HMAC is the proof, and a certificate
        # would add nothing to it, while deployments behind an internal CA or a VPN, whose CA
        # this container does not hold, would then never pass. No redirect is followed: the
        # proof must come from the plugin host itself.
        async with (
            httpx.AsyncClient(
                transport=self._transport,
                timeout=PROBE_STEP_TIMEOUT_SECONDS,
                follow_redirects=False,
                verify=False,
            ) as client,
            client.stream(
                "GET", f"{origin}{INSTANCE_PATH}", params={CHALLENGE_PARAMETER: challenge}
            ) as response,
        ):
            if response.status_code != 200:
                status = response.status_code
                return _Failure(f"status_{status}", conclusive=status != 429 and status < 500)
            body = bytearray()
            # Raw bytes: nothing is decompressed, so the limit is on what crosses the wire.
            async for chunk in response.aiter_raw():
                body += chunk
                if len(body) > MAX_ANSWER_BYTES:
                    return _Failure("not_a_proof", conclusive=True)
            return bytes(body)


def _release(lock_key: str, lock_token: str) -> None:
    """Delete the probe lock if this probe still holds it.

    Read, compare, delete: not atomic, but the lock outlives the probe that holds it
    (`PROBE_LOCK_SECONDS`), so between the read and the delete it can only pass to another
    probe if this process stalls for seconds. An atomic compare-and-delete would need a Lua
    script on django-redis's raw connection, with the cache's own key and value encoding.
    """
    if cache.get(lock_key) == lock_token:
        cache.delete(lock_key)
