"""The EpicStaff HTTP calls the benchmark needs. Standard library only."""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request

VOLATILE_GRAPH_KEYS = frozenset({"created_at", "updated_at", "save_version"})


class ApiError(Exception):
    def __init__(self, status: int | None, message: str):
        super().__init__(f"HTTP {status}: {message}" if status else message)
        self.status = status


class Api:
    def __init__(self, base_url: str, api_key: str, org_id: str, timeout_s: float = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._headers = {
            "X-Api-Key": api_key,
            "X-Organization-Id": str(org_id),
            "Content-Type": "application/json",
        }

    def request(self, method: str, path: str, body=None, query: dict | None = None):
        url = self.base_url + path + ("?" + urllib.parse.urlencode(query) if query else "")
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, headers=self._headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                raw = response.read()
                return response.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as error:
            raise ApiError(error.code, error.read(300).decode("utf-8", "replace")) from error
        except (urllib.error.URLError, OSError) as error:
            raise ApiError(None, f"{type(error).__name__}: {error}") from error

    def get_graph(self, graph_id: int) -> dict:
        return self.request("GET", f"/api/graphs/{graph_id}/")[1]

    def start_session(self, graph_id: int, variables: dict | None) -> tuple[int, int]:
        body = {"graph_id": graph_id, **({"variables": variables} if variables else {})}
        status, payload = self.request("POST", "/api/run-session/", body)
        session_id = (payload or {}).get("session_id")
        if not isinstance(session_id, int):
            raise ApiError(status, "run-session answered without a session_id")
        return status, session_id

    def stop_session(self, session_id: int) -> None:
        self.request("POST", f"/api/sessions/{session_id}/stop/")

    def in_flight(self, graph_id: int) -> int:
        query = {"graph_id": graph_id, "status": "pending,run"}
        counts = self.request("GET", "/api/sessions/statuses/", query=query)[1] or {}
        return sum(counts.get(str(graph_id), {}).values())

    def delete_sessions(self, session_ids: list[int], batch: int = 500) -> int:
        deleted = 0
        for start in range(0, len(session_ids), batch):
            chunk = session_ids[start : start + batch]
            deleted += self.request("POST", "/api/sessions/bulk_delete/", {"ids": chunk})[1][
                "deleted"
            ]
        return deleted

    def sessions_since(self, graph_id: int, created_after_iso: str) -> list[dict]:
        """Session rows (status, created_at, finished_at) — the fallback when crew has no BENCH lines."""
        rows, offset = [], 0
        while True:
            query = {
                "graph_id": graph_id,
                "created_at_after": created_after_iso,
                "detailed": "false",
                "limit": 1000,
                "offset": offset,
            }
            page = self.request("GET", "/api/sessions/", query=query)[1]
            rows.extend(page["results"])
            if not page.get("next"):
                return rows
            offset += 1000


def graph_hash(graph: dict) -> str:
    """Hash of a graph definition without timestamps, so any real edit changes it."""

    def strip(value):
        if isinstance(value, dict):
            return {
                key: strip(item) for key, item in value.items() if key not in VOLATILE_GRAPH_KEYS
            }
        if isinstance(value, list):
            return [strip(item) for item in value]
        return value

    encoded = json.dumps(strip(graph), sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]
