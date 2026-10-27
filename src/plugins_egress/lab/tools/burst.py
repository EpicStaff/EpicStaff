"""Lab only: a burst of CONNECTs, one per name, sent together; prints each name's answer.

  burst.py <count> <tag>   CONNECT q<n>-<tag>.slow.rebind.test:443 for n in 0..count-1, as PROXY_URL's user

One line per name: the name, seconds to the answer, the status code and X-Squid-Error.
"""

import base64
import os
import socket
import sys
import threading
import time
from urllib.parse import unquote, urlsplit

proxy = urlsplit(os.environ["PROXY_URL"])
token = base64.b64encode(f"{unquote(proxy.username)}:{unquote(proxy.password)}".encode()).decode()
count, tag = int(sys.argv[1]), sys.argv[2]
answers = {}


def ask(index: int) -> None:
    name = f"q{index}-{tag}.slow.rebind.test"
    started = time.time()
    with socket.create_connection((proxy.hostname, proxy.port), 30) as connection:
        connection.sendall(
            f"CONNECT {name}:443 HTTP/1.1\r\nHost: {name}:443\r\nProxy-Authorization: Basic {token}\r\n\r\n".encode()
        )
        head = connection.recv(4096).decode("latin-1").split("\r\n")
    error = next(
        (
            line.split(":", 1)[1].split()[0]
            for line in head
            if line.lower().startswith("x-squid-error")
        ),
        "-",
    )
    answers[name] = f"{time.time() - started:.2f} {head[0].split()[1]} {error}"


threads = [threading.Thread(target=ask, args=(index,)) for index in range(count)]
for thread in threads:
    thread.start()
    time.sleep(0.05)
for thread in threads:
    thread.join()
for name in sorted(answers):
    print(name, answers[name])
