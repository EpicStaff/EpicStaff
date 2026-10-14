"""Deterministic OpenAI-compatible LLM stub for the end-to-end suite (stdlib only).

The e2e stack points its LLM model `base_url` and `KNOWLEDGE_CUSTOM_EMBED_BASE_URL` at this
server, so flows that use an agent or naive RAG run without a real provider and give
predictable output.

Contract:

POST /v1/chat/completions
    The reply is chosen from the request, in this order:
    1. The conversation has a `role: tool` message -> text `ANSWER: <content of the last tool
       message>`. No tool call, so the agent loop stops.
    2. `tools` is set and one of them is named `search_*` -> one tool call to the first such
       tool, arguments `{"query": <content of the last user message>}`, finish reason
       `tool_calls`.
    3. Otherwise -> text `OK: <content of the last user message>`.
    With `stream: true` the reply is an SSE stream of `chat.completion.chunk` objects, then a
    usage chunk with empty `choices` when `stream_options.include_usage` is true, then
    `data: [DONE]`. Without it, one `chat.completion` object. The request `model` is echoed.
    `tool_choice`, `response_format` and `n` are ignored: a forced tool call (such as the
    agent's `submit_final_answer`) or a structured-output schema will not be honoured, so
    flows that need either cannot run against this mock.

POST /v1/embeddings
    `input` is a string or a list. Every input gets the same non-zero vector of
    `EMBEDDING_DIMENSION` floats, so any query matches any chunk with cosine similarity 1.0.
    `encoding_format: "base64"` is honoured (little-endian float32), as the openai SDK asks
    for it by default.

GET /__calls
    Every request received so far (except `/health` and `/__calls`): method, path (without the
    query string), parsed JSON body and timestamp.

DELETE /__calls
    Clear the log; answers `{"cleared": <number of removed entries>}`.

GET /health
    `{"status": "ok"}`.

Routes match on the path without its query string. Errors are JSON: 404 for an unknown path,
411 for a chunked request body (only `Content-Length` bodies are read), 400 for an invalid
`Content-Length`, unparseable JSON, or a JSON body that is not an object.

Run: `python server.py` (listens on 0.0.0.0, port `MOCK_LLM_PORT`, default 8080).
"""

import base64
import json
import os
import struct
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

EMBEDDING_DIMENSION = 8
EMBEDDING_VECTOR = [1.0 / EMBEDDING_DIMENSION**0.5] * EMBEDDING_DIMENSION
SEARCH_TOOL_PREFIX = "search_"
DEFAULT_PORT = 8080


class CallLog:
    """Thread-safe record of every request the server received."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: list[dict] = []

    def record(self, method: str, path: str, body: object) -> None:
        call = {"method": method, "path": path, "body": body, "timestamp": time.time()}
        with self._lock:
            self._calls.append(call)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self._calls)

    def clear(self) -> int:
        with self._lock:
            cleared = len(self._calls)
            self._calls.clear()
            return cleared


CALL_LOG = CallLog()


class RequestBodyError(Exception):
    """The request body cannot be used; answered with `status` and `message`.

    `body_unread` means bytes may still be on the socket, so the connection must be closed
    rather than parsed as the next request.
    """

    def __init__(self, status: HTTPStatus, message: str, body_unread: bool) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.body_unread = body_unread


def new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:24]}"


def content_as_text(content: object) -> str:
    """Flatten message content: a string, or a list of `{"type": "text", "text": ...}` parts."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return str(content)


def last_message_text(messages: list[dict], role: str) -> str | None:
    for message in reversed(messages):
        if message.get("role") == role:
            return content_as_text(message.get("content"))
    return None


def first_search_tool_name(tools: list[dict]) -> str | None:
    for tool in tools:
        name = tool.get("function", {}).get("name", "")
        if name.startswith(SEARCH_TOOL_PREFIX):
            return name
    return None


def count_tokens(text: str) -> int:
    """Rough token count; only needs to be non-zero and stable."""
    return max(1, len(text.split()))


def plan_reply(request: dict) -> dict:
    """Decide the assistant reply.

    Returns:
        `{"content": str}` for a text answer, or `{"tool_call": {...}}` with `id`, `name`
        and JSON-encoded `arguments` for a tool call.
    """
    messages = request.get("messages") or []
    last_user_text = last_message_text(messages, "user") or ""

    last_tool_text = last_message_text(messages, "tool")
    if last_tool_text is not None:
        return {"content": f"ANSWER: {last_tool_text}"}

    search_tool_name = first_search_tool_name(request.get("tools") or [])
    if search_tool_name is not None:
        return {
            "tool_call": {
                "id": new_id("call_"),
                "name": search_tool_name,
                "arguments": json.dumps({"query": last_user_text}),
            }
        }

    return {"content": f"OK: {last_user_text}"}


def build_usage(request: dict, reply: dict) -> dict:
    prompt_text = " ".join(
        content_as_text(message.get("content")) for message in request.get("messages") or []
    )
    if "tool_call" in reply:
        completion_text = reply["tool_call"]["arguments"]
    else:
        completion_text = reply["content"]
    prompt_tokens = count_tokens(prompt_text)
    completion_tokens = count_tokens(completion_text)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def tool_call_object(tool_call: dict, index: int | None = None) -> dict:
    """OpenAI tool call; stream deltas carry `index`, full messages do not."""
    call = {
        "id": tool_call["id"],
        "type": "function",
        "function": {"name": tool_call["name"], "arguments": tool_call["arguments"]},
    }
    if index is not None:
        call = {"index": index, **call}
    return call


def finish_reason_for(reply: dict) -> str:
    return "tool_calls" if "tool_call" in reply else "stop"


def build_completion(request: dict, reply: dict) -> dict:
    message: dict = {"role": "assistant", "content": reply.get("content")}
    if "tool_call" in reply:
        message["tool_calls"] = [tool_call_object(reply["tool_call"])]
    return {
        "id": new_id("chatcmpl-"),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.get("model", ""),
        "choices": [
            {
                "index": 0,
                "message": message,
                "logprobs": None,
                "finish_reason": finish_reason_for(reply),
            }
        ],
        "usage": build_usage(request, reply),
    }


def build_stream_chunks(request: dict, reply: dict) -> list[dict]:
    """Chunks of one streamed reply: content or tool call, finish, optional usage."""
    completion_id = new_id("chatcmpl-")
    created = int(time.time())
    model = request.get("model", "")

    def chunk(choices: list[dict], **extra: object) -> dict:
        return {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": choices,
            **extra,
        }

    def choice(delta: dict, finish_reason: str | None = None) -> dict:
        return {"index": 0, "delta": delta, "logprobs": None, "finish_reason": finish_reason}

    if "tool_call" in reply:
        first_delta = {
            "role": "assistant",
            "content": None,
            "tool_calls": [tool_call_object(reply["tool_call"], index=0)],
        }
    else:
        first_delta = {"role": "assistant", "content": reply["content"]}

    chunks = [
        chunk([choice(first_delta)]),
        chunk([choice({}, finish_reason_for(reply))]),
    ]
    stream_options = request.get("stream_options") or {}
    if stream_options.get("include_usage"):
        chunks.append(chunk([], usage=build_usage(request, reply)))
    return chunks


def embedding_inputs(raw_input: object) -> list[object]:
    if isinstance(raw_input, list):
        return raw_input
    return [raw_input]


def encode_embedding(encoding_format: str | None) -> list[float] | str:
    if encoding_format == "base64":
        packed = struct.pack(f"<{EMBEDDING_DIMENSION}f", *EMBEDDING_VECTOR)
        return base64.b64encode(packed).decode("ascii")
    return list(EMBEDDING_VECTOR)


def build_embeddings(request: dict) -> dict:
    inputs = embedding_inputs(request.get("input"))
    embedding = encode_embedding(request.get("encoding_format"))
    prompt_tokens = sum(count_tokens(str(item)) for item in inputs)
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": index, "embedding": embedding}
            for index in range(len(inputs))
        ],
        "model": request.get("model", ""),
        "usage": {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens},
    }


class MockLLMHandler(BaseHTTPRequestHandler):
    # HTTP/1.1 keeps connections alive for litellm's pooled clients; every response
    # therefore sets Content-Length or closes the connection itself.
    protocol_version = "HTTP/1.1"

    @property
    def route(self) -> str:
        return urlsplit(self.path).path

    def do_GET(self) -> None:
        # The healthcheck and the log itself are not recorded: they would bury the LLM calls.
        if self.route == "/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
        elif self.route == "/__calls":
            self._send_json(HTTPStatus.OK, CALL_LOG.snapshot())
        else:
            CALL_LOG.record("GET", self.route, None)
            self._send_error(HTTPStatus.NOT_FOUND, f"Unknown path: {self.route}")

    def do_DELETE(self) -> None:
        if self.route == "/__calls":
            self._send_json(HTTPStatus.OK, {"cleared": CALL_LOG.clear()})
        else:
            CALL_LOG.record("DELETE", self.route, None)
            self._send_error(HTTPStatus.NOT_FOUND, f"Unknown path: {self.route}")

    def do_POST(self) -> None:
        try:
            request = self._read_json_object()
        except RequestBodyError as error:
            if error.body_unread:
                self.close_connection = True
            self._send_error(error.status, error.message)
            return

        if self.route == "/v1/chat/completions":
            self._handle_chat_completion(request)
        elif self.route == "/v1/embeddings":
            self._send_json(HTTPStatus.OK, build_embeddings(request))
        else:
            self._send_error(HTTPStatus.NOT_FOUND, f"Unknown path: {self.route}")

    def _read_json_object(self) -> dict:
        """Read and record the POST body; it must be a `Content-Length` JSON object."""
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            CALL_LOG.record("POST", self.route, None)
            raise RequestBodyError(
                HTTPStatus.LENGTH_REQUIRED, "Chunked request bodies are not supported", True
            )

        raw_length = self.headers.get("Content-Length") or "0"
        try:
            length = int(raw_length)
            if length < 0:
                raise ValueError
        except ValueError:
            CALL_LOG.record("POST", self.route, None)
            raise RequestBodyError(
                HTTPStatus.BAD_REQUEST, f"Invalid Content-Length: {raw_length!r}", True
            ) from None

        raw_body = self.rfile.read(length)
        try:
            request = json.loads(raw_body or b"{}")
        except json.JSONDecodeError as error:
            CALL_LOG.record("POST", self.route, raw_body.decode("utf-8", errors="replace"))
            raise RequestBodyError(
                HTTPStatus.BAD_REQUEST, f"Invalid JSON body: {error}", False
            ) from None

        CALL_LOG.record("POST", self.route, request)
        if not isinstance(request, dict):
            raise RequestBodyError(
                HTTPStatus.BAD_REQUEST,
                f"JSON body must be an object, got {type(request).__name__}",
                False,
            )
        return request

    def _handle_chat_completion(self, request: dict) -> None:
        reply = plan_reply(request)
        if request.get("stream"):
            self._send_stream(build_stream_chunks(request, reply))
        else:
            self._send_json(HTTPStatus.OK, build_completion(request, reply))

    def _send_stream(self, chunks: list[dict]) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        # No Content-Length on a stream: closing the connection marks its end.
        self.send_header("Connection", "close")
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True

    def _send_json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json(status, {"error": {"message": message, "code": status.value}})

    def log_message(self, format: str, *args: object) -> None:
        print(f"[mock-llm] {self.address_string()} {format % args}", flush=True)


def main() -> None:
    port = int(os.environ.get("MOCK_LLM_PORT", DEFAULT_PORT))
    server = ThreadingHTTPServer(("0.0.0.0", port), MockLLMHandler)
    print(f"[mock-llm] listening on 0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
