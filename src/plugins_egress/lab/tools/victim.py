"""Lab only: a private service on the proxy's way out. Logs every TCP connection it gets on 443."""

import socket
import time

listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("0.0.0.0", 443))
listener.listen(16)
print("victim listening on 443", flush=True)
while True:
    connection, peer = listener.accept()
    print(f"{time.time():.3f} VICTIM CONNECTED from {peer[0]}", flush=True)
    connection.close()
