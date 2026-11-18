"""A stand-in for the knowledge service, answered through the client's own transport."""

import httpx

from tables.clients.knowledge import KnowledgeClient


class FakeKnowledgeService:
    """Answers each request with the next queued response and records what it received."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.requests: list[tuple[str, str, bytes]] = []

    def __call__(self, request: httpx.Request):
        # Reading the body consumes a streamed upload exactly as the real server would.
        self.requests.append((request.method, request.url.path, request.read()))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def respond_with(self, *responses) -> None:
        self._responses.extend(responses)

    def client(self, **_client_options) -> KnowledgeClient:
        return KnowledgeClient(transport=httpx.MockTransport(self))
