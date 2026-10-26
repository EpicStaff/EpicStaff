"""Lab only: one plugin floods the egress proxy with CONNECTs and counts the answers.

  flood.py passwords <seconds> <connections>  as PROXY_URL's user, with a new random password each
  flood.py hosts <seconds> <connections>      with PROXY_URL's own credentials, to a new name under
                                              .flood.test each (no such name is on any list)

Each request opens a connection of its own and closes it with a reset, so the flood leaves no
connections waiting in TIME_WAIT and never runs out of local ports. Prints one line: requests,
requests per second and the count of each answer. Never prints a credential.
"""

import asyncio
import base64
import collections
import os
import secrets
import socket
import struct
import sys
import time
from urllib.parse import unquote, urlsplit

DECLARED_HOST = "geocoding-api.open-meteo.com"


def request(mode: str, user: str, password: str) -> bytes:
    if mode == "passwords":
        password, host = secrets.token_urlsafe(24), DECLARED_HOST
    else:
        host = f"{secrets.token_hex(6)}.flood.test"
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\nProxy-Authorization: Basic {token}\r\n\r\n".encode()


async def flood(mode: str, deadline: float, counts: collections.Counter) -> None:
    proxy = urlsplit(os.environ["PROXY_URL"])
    user, password = unquote(proxy.username), unquote(proxy.password)
    while time.monotonic() < deadline:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(proxy.hostname, proxy.port), 10
            )
        except (OSError, TimeoutError):
            counts["no-connection"] += 1
            await asyncio.sleep(0.1)
            continue
        try:
            writer.write(request(mode, user, password))
            await writer.drain()
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 60)
            counts[head.split(b" ", 2)[1].decode()] += 1
        except (OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            counts["dropped"] += 1
        finally:
            connection = writer.get_extra_info("socket")
            if connection is not None:
                connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            writer.close()


async def main() -> None:
    mode, seconds, connections = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])
    counts: collections.Counter = collections.Counter()
    started = time.monotonic()
    await asyncio.gather(*(flood(mode, started + seconds, counts) for _ in range(connections)))
    answered = sum(count for answer, count in counts.items() if answer.isdigit())
    tally = " ".join(f"{answer}={count}" for answer, count in sorted(counts.items()))
    print(f"requests={answered} per_second={answered / (time.monotonic() - started):.0f} {tally}")


asyncio.run(main())
