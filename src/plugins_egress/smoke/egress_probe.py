"""Ask plugins_egress the way a plugin backend does, and print status codes only.

The egress lab (../lab/run.sh) and the smoke check (check_egress.sh) both run it. It takes the
proxy URL a plugin gets, never credentials on its command line:

  --proxy env        PROXY_URL from this process's environment (the lab)
  --proxy same-uid   HTTPS_PROXY of another process of this UID, read from /proc/<pid>/environ as
                     the plugin itself could (the smoke check, run as the plugin's UID)

--no-credentials sends none, --wrong-password sends the user with another password. It never
prints a password, a Basic token or the proxy URL.

Commands:
  connect <host:port>   a CONNECT, the authority sent as given: connect=<status> squid=<error>
  get <https url>       CONNECT, TLS, then a GET: connect=<status> http=<status> squid=<error>
  plain <http url>      a plain-HTTP request through the proxy: http=<status> squid=<error>
  direct <host> <port>  a TCP connection that bypasses the proxy: direct=<outcome>
  resolve <name>        a DNS lookup: resolve=ok or resolve=failed
  open <path>           opens a file for reading: open=ok or open=<errno name>
  user                  the proxy user: user=<identifier>
  count-secret          reads stdin: secret=<occurrences of the password or its Basic token>

Standard library only; run with `python -I`.
"""

import argparse
import base64
import errno
import os
import secrets
import socket
import ssl
import sys
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

TIMEOUT_SECONDS = 20
# Some APIs refuse a request without one.
USER_AGENT = "epicstaff-egress-probe"


@dataclass(frozen=True)
class Proxy:
    host: str
    port: int
    user: str
    password: str

    def authorization(self, *, credentials: bool, wrong_password: bool) -> str:
        if not credentials:
            return ""
        password = secrets.token_urlsafe(24) if wrong_password else self.password
        token = base64.b64encode(f"{self.user}:{password}".encode()).decode()
        return f"Proxy-Authorization: Basic {token}\r\n"


def read_proxy_url(source: str) -> str:
    if source == "env":
        return os.environ["PROXY_URL"]
    if source == "same-uid":
        for pid in sorted(filter(str.isdigit, os.listdir("/proc")), key=int):
            if int(pid) == os.getpid():
                continue
            try:
                if os.stat(f"/proc/{pid}").st_uid != os.getuid():
                    continue
                with open(f"/proc/{pid}/environ", "rb") as environ:
                    entries = environ.read().split(b"\0")
            except OSError:
                continue
            for entry in entries:
                name, _, value = entry.partition(b"=")
                if name == b"HTTPS_PROXY":
                    return value.decode()
        raise SystemExit("probe: no other process of this UID has HTTPS_PROXY")
    raise SystemExit("probe: --proxy is env or same-uid")


def parse_proxy(url: str) -> Proxy:
    parts = urlsplit(url)
    return Proxy(
        parts.hostname,
        parts.port or 3128,
        unquote(parts.username or ""),
        unquote(parts.password or ""),
    )


def read_head(connection: socket.socket) -> tuple[int, str]:
    """The status code and X-Squid-Error of the proxy's answer; the body is left unread."""
    received = b""
    while b"\r\n\r\n" not in received:
        chunk = connection.recv(4096)
        if not chunk:
            break
        received += chunk
    lines = received.split(b"\r\n\r\n", 1)[0].decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1]) if lines and len(lines[0].split()) > 1 else 0
    squid_error = next(
        (
            line.split(":", 1)[1].strip().split()[0]
            for line in lines[1:]
            if line.lower().startswith("x-squid-error:")
        ),
        "-",
    )
    return status, squid_error


def open_tunnel(proxy: Proxy, authority: str, authorization: str) -> tuple[socket.socket, int, str]:
    connection = socket.create_connection((proxy.host, proxy.port), TIMEOUT_SECONDS)
    connection.sendall(
        f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n{authorization}\r\n".encode()
    )
    status, squid_error = read_head(connection)
    return connection, status, squid_error


def command_connect(proxy: Proxy, authorization: str, authority: str) -> str:
    connection, status, squid_error = open_tunnel(proxy, authority, authorization)
    connection.close()
    return f"connect={status} squid={squid_error}"


def command_get(proxy: Proxy, authorization: str, url: str) -> str:
    parts = urlsplit(url)
    connection, status, squid_error = open_tunnel(
        proxy, f"{parts.hostname}:{parts.port or 443}", authorization
    )
    if status != 200:
        connection.close()
        return f"connect={status} http=- squid={squid_error}"
    with ssl.create_default_context().wrap_socket(
        connection, server_hostname=parts.hostname
    ) as tls:
        path = parts.path or "/"
        if parts.query:
            path += f"?{parts.query}"
        tls.sendall(
            f"GET {path} HTTP/1.1\r\nHost: {parts.hostname}\r\nUser-Agent: {USER_AGENT}\r\n"
            "Connection: close\r\n\r\n".encode()
        )
        http_status, _ = read_head(tls)
    return f"connect={status} http={http_status} squid={squid_error}"


def command_plain(proxy: Proxy, authorization: str, url: str) -> str:
    with socket.create_connection((proxy.host, proxy.port), TIMEOUT_SECONDS) as connection:
        host = urlsplit(url).hostname
        connection.sendall(
            f"GET {url} HTTP/1.1\r\nHost: {host}\r\n{authorization}Connection: close\r\n\r\n".encode()
        )
        status, squid_error = read_head(connection)
    return f"http={status} squid={squid_error}"


def command_direct(host: str, port: str) -> str:
    try:
        socket.create_connection((host, int(port)), 5).close()
    except TimeoutError:
        return "direct=timeout"
    except OSError as error:
        return f"direct={errno.errorcode.get(error.errno, type(error).__name__)}"
    return "direct=connected"


def command_resolve(name: str) -> str:
    try:
        socket.getaddrinfo(name, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return "resolve=failed"
    return "resolve=ok"


def command_open(path: str) -> str:
    try:
        with open(path, "rb"):
            return "open=ok"
    except OSError as error:
        return f"open={errno.errorcode.get(error.errno, type(error).__name__)}"


def command_count_secret(proxy: Proxy) -> str:
    text = sys.stdin.buffer.read().decode("utf-8", "replace")
    token = base64.b64encode(f"{proxy.user}:{proxy.password}".encode()).decode()
    return f"secret={text.count(proxy.password) + text.count(token)}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--proxy", default="env")
    parser.add_argument("--no-credentials", action="store_true")
    parser.add_argument("--wrong-password", action="store_true")
    parser.add_argument("command")
    parser.add_argument("arguments", nargs="*")
    options = parser.parse_args()

    if options.command == "direct":
        print(command_direct(*options.arguments))
        return
    if options.command == "resolve":
        print(command_resolve(*options.arguments))
        return
    if options.command == "open":
        print(command_open(*options.arguments))
        return
    proxy = parse_proxy(read_proxy_url(options.proxy))
    if options.command == "count-secret":
        print(command_count_secret(proxy))
        return
    if options.command == "user":
        print(f"user={proxy.user}")
        return
    authorization = proxy.authorization(
        credentials=not options.no_credentials, wrong_password=options.wrong_password
    )
    commands = {"connect": command_connect, "get": command_get, "plain": command_plain}
    try:
        print(commands[options.command](proxy, authorization, *options.arguments))
    except OSError as error:
        print(f"error={errno.errorcode.get(error.errno, type(error).__name__)}")


if __name__ == "__main__":
    main()
