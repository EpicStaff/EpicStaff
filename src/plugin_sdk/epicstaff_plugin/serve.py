"""Run a plugin's backend as the EpicStaff node does: `python -I -m epicstaff_plugin.serve`.

Reads the runtime file, imports the ASGI app `EPICSTAFF_PLUGIN_ENTRYPOINT` names
(`module.path:attribute`), and serves it with uvicorn behind the health endpoint, the hook
dispatch and the context check, in that order. So every request except `GET /_epicstaff/health`
needs proof that EpicStaff sent it: a hook call a valid hook assertion, anything else a valid
gateway context. Other plugins on the node can reach this port, and those two are what tell
EpicStaff's requests apart from theirs.

Importing the entrypoint module registers the plugin's hook handlers
(`epicstaff_plugin.hooks.hook_registry`).

On the node the port belongs to the platform: the node binds it, holds it across restarts, and
passes the listening socket in as the file descriptor `EPICSTAFF_PLUGIN_LISTEN_FD` names, so
no other process on the node can take the port while the plugin restarts. Without that
variable the runner binds `0.0.0.0:$PORT` itself.

`create_app` is the app both the node's runner and `epicstaff-plugin dev` serve; on an author's
machine, run the backend with `epicstaff-plugin dev`, which serves it on a loopback address
and reloads it when the source changes.
"""

import errno
import importlib
import os
import re
import socket
import sys

from epicstaff_plugin.asgi import ASGIApp
from epicstaff_plugin.client.epicstaff_client import EpicStaffClient
from epicstaff_plugin.contracts.manifest import ENTRYPOINT_PATTERN
from epicstaff_plugin.contracts.runtime import (
    ENTRYPOINT_ENVIRONMENT_VARIABLE,
    LISTEN_FD_ENVIRONMENT_VARIABLE,
    PORT_ENVIRONMENT_VARIABLE,
)
from epicstaff_plugin.gateway.asgi_middleware import EpicStaffContextMiddleware
from epicstaff_plugin.gateway.context_verifier import ContextVerifier
from epicstaff_plugin.health import HealthCheckMiddleware
from epicstaff_plugin.hooks.assertion_verifier import HookAssertionVerifier
from epicstaff_plugin.hooks.hook_dispatch import HookDispatchMiddleware
from epicstaff_plugin.hooks.hook_registry import HookRegistry, hook_registry
from epicstaff_plugin.runtime.runtime_config import (
    RuntimeConfig,
    RuntimeConfigError,
    runtime_config,
)

LISTEN_HOST = "0.0.0.0"
_TCP_FAMILIES = (socket.AF_INET, socket.AF_INET6)
EXIT_START_FAILED = 1


class ServeError(Exception):
    """The plugin cannot be started: a missing variable, a bad port, socket or entrypoint."""


def build_app(
    app: ASGIApp,
    runtime: RuntimeConfig,
    *,
    hooks: HookRegistry | None = None,
    epicstaff: EpicStaffClient | None = None,
) -> ASGIApp:
    """Wrap the plugin's app the way the node serves it: health, hook dispatch, context check.

    `hooks` defaults to the process-wide `hook_registry`, and `epicstaff` (the client hook
    handlers get) to a new client over `runtime`.
    """
    context_verifier = ContextVerifier(runtime)
    return HealthCheckMiddleware(
        HookDispatchMiddleware(
            EpicStaffContextMiddleware(app, context_verifier),
            # One key lookup for both checks: they trust the same keys, under one
            # download budget.
            HookAssertionVerifier(context_verifier.signing_keys),
            hook_registry if hooks is None else hooks,
            EpicStaffClient(runtime) if epicstaff is None else epicstaff,
        )
    )


def create_app() -> ASGIApp:
    """Return the plugin's app as the node serves it, from this process's environment.

    Reads the runtime file `EPICSTAFF_PLUGIN_RUNTIME_FILE` names and imports the app
    `EPICSTAFF_PLUGIN_ENTRYPOINT` names, then wraps it with `build_app`. A uvicorn app factory:
    `epicstaff-plugin dev` serves `epicstaff_plugin.serve:create_app` with `factory=True`, so
    each reload builds the app anew.

    Raises:
        RuntimeConfigError: The runtime file is not named, unreadable or invalid.
        ServeError: The entrypoint is not set, malformed, or does not import.
    """
    runtime = runtime_config()
    entrypoint = os.environ.get(ENTRYPOINT_ENVIRONMENT_VARIABLE)
    if not entrypoint:
        raise ServeError(f"{ENTRYPOINT_ENVIRONMENT_VARIABLE} is not set")
    return build_app(load_entrypoint(entrypoint), runtime)


def load_entrypoint(entrypoint: str) -> ASGIApp:
    """Import the ASGI app an entrypoint (`module.path:attribute`) names.

    Raises:
        ServeError: The entrypoint is malformed, its module does not import, or it names no
            callable.
    """
    if not re.match(ENTRYPOINT_PATTERN, entrypoint):
        raise ServeError(
            f"{ENTRYPOINT_ENVIRONMENT_VARIABLE} {entrypoint!r} is not module.path:attribute"
        )
    module_name, _, attribute = entrypoint.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        raise ServeError(f"cannot import {module_name}: {error}") from error
    app = getattr(module, attribute, None)
    if not callable(app):
        raise ServeError(f"{module_name} has no ASGI app named {attribute}")
    return app


def listen_port() -> int:
    """Return the port in `PORT`.

    Raises:
        ServeError: `PORT` is not set or is not a port number.
    """
    value = os.environ.get(PORT_ENVIRONMENT_VARIABLE, "")
    if not value.isdigit() or not 1 <= int(value) <= 65535:
        raise ServeError(f"{PORT_ENVIRONMENT_VARIABLE} must be a port number, not {value!r}")
    return int(value)


def inherited_listen_fd() -> int | None:
    """Return the listening socket the node passed in, or None when the runner binds its own.

    The descriptor is made non-inheritable, so a process the plugin starts never holds it.

    Raises:
        ServeError: `EPICSTAFF_PLUGIN_LISTEN_FD` is set but is not a descriptor number, or the
            descriptor is not a listening TCP socket.
    """
    value = os.environ.get(LISTEN_FD_ENVIRONMENT_VARIABLE)
    if value is None:
        return None
    if not value.isdigit():
        raise ServeError(
            f"{LISTEN_FD_ENVIRONMENT_VARIABLE} must be a file descriptor number, not {value!r}"
        )
    fd = int(value)
    _check_listening_tcp_socket(fd)
    os.set_inheritable(fd, False)
    return fd


def _check_listening_tcp_socket(fd: int) -> None:
    what = f"{LISTEN_FD_ENVIRONMENT_VARIABLE} {fd}"
    try:
        duplicate = os.dup(fd)
    except OSError as error:
        raise ServeError(f"{what} is not an open file descriptor: {error.strerror}") from None
    # A duplicate, so closing the probe leaves the node's descriptor open.
    try:
        probe = socket.socket(fileno=duplicate)
    except OSError as error:
        os.close(duplicate)
        raise ServeError(f"{what} is not a socket: {error.strerror}") from None
    with probe:
        if probe.family not in _TCP_FAMILIES or probe.type != socket.SOCK_STREAM:
            raise ServeError(f"{what} is not a TCP socket")
        if not _is_listening(probe):
            raise ServeError(f"{what} is a TCP socket that is not listening")


def _is_listening(probe: socket.socket) -> bool:
    try:
        return probe.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) != 0
    except OSError as error:
        if error.errno != errno.ENOPROTOOPT:
            raise
    # macOS cannot say whether a socket listens (the node runs Linux, which can): accept a
    # bound socket with no peer.
    try:
        probe.getpeername()
    except OSError:
        return probe.getsockname()[1] != 0
    return False


def main() -> int:
    """Start the plugin and serve until stopped; return the exit code if it cannot start."""
    try:
        app = create_app()
        listen_fd = inherited_listen_fd()
        # The node's socket is used as it is; `PORT` is then only for information.
        bind = (
            {"fd": listen_fd}
            if listen_fd is not None
            else {"host": LISTEN_HOST, "port": listen_port()}
        )
    except (RuntimeConfigError, ServeError) as error:
        print(f"epicstaff_plugin.serve: {error}", file=sys.stderr)
        return EXIT_START_FAILED
    # Imported here: uvicorn is a dependency of the plugin's lock, not of the SDK.
    try:
        import uvicorn
    except ImportError:
        print(
            "epicstaff_plugin.serve: uvicorn is not installed; pin it in backend/requirements.lock",
            file=sys.stderr,
        )
        return EXIT_START_FAILED

    uvicorn.run(
        app,
        **bind,
        workers=1,
        # The gateway is the only proxy in front, and the plugin never needs the client's
        # address from forwarded headers.
        proxy_headers=False,
        server_header=False,
        lifespan="on",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
