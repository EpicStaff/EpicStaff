"""Small HTTP servers on 127.0.0.1, for tests of which way a client's requests really go."""

import json
import socketserver
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# What the egress proxy answers a CONNECT to a host the plugin did not declare.
REFUSAL = (
    b"HTTP/1.1 403 Forbidden\r\n"
    b"X-Squid-Error: ERR_HOST_NOT_ALLOWED 0\r\n"
    b"Content-Length: 0\r\n"
    b"Connection: close\r\n\r\n"
)


class _ProxyHandler(socketserver.StreamRequestHandler):
    def handle(self):
        head = []
        while (line := self.rfile.readline()) not in (b"\r\n", b"\n", b""):
            head.append(line.decode("latin-1").rstrip("\r\n"))
        self.server.requests.append(head)
        self.wfile.write(REFUSAL)


class RefusingProxy(socketserver.ThreadingTCPServer):
    """Records the head of every request a client sends it, and refuses each like the egress proxy."""

    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _ProxyHandler)
        self.requests = []

    @property
    def port(self):
        return self.server_address[1]


class _ApiHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.paths.append(self.path.partition("?")[0])
        body = json.dumps({"count": 0, "results": []}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class EmptyApi(ThreadingHTTPServer):
    """Answers every GET with an empty page of results, recording the path asked for."""

    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _ApiHandler)
        self.paths = []

    @property
    def port(self):
        return self.server_address[1]


@contextmanager
def serving(server):
    """Serve in a background thread for the block: `with serving(RefusingProxy()) as proxy:`."""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
