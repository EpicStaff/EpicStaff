"""The node lab's stand-in for plugins_db and the egress proxy as a flood sees them.

On 5432 and 3128 it accepts a connection and holds it, sending nothing, as PostgreSQL holds a
connection whose client never answers its password challenge; it closes its side when the client
closes. On 8080 it accepts and closes at once, for a flood of short connections.
"""

import selectors
import socket

HOLDING_PORTS = (5432, 3128)
CLOSING_PORT = 8080

selector = selectors.DefaultSelector()
for port in (*HOLDING_PORTS, CLOSING_PORT):
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("0.0.0.0", port))
    listener.listen(4096)
    listener.setblocking(False)
    selector.register(listener, selectors.EVENT_READ, port)
print("holder ready", flush=True)
while True:
    for key, _ in selector.select():
        if key.data == "held":
            try:
                data = key.fileobj.recv(4096)
            except OSError:
                data = b""
            if not data:
                selector.unregister(key.fileobj)
                key.fileobj.close()
            continue
        connection, _ = key.fileobj.accept()
        if key.data == CLOSING_PORT:
            connection.close()
            continue
        connection.setblocking(False)
        selector.register(connection, selectors.EVENT_READ, "held")
