"""An httpx MockTransport that behaves like the Django endpoints the chat service calls."""

import json
import re

import httpx


class FakeDjango:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.graphs: dict[int, dict] = {}          # graph_id -> {"org_id", "start_variables", "output_map"}
        self.sessions: dict[int, dict] = {}        # session_id -> {"org_id", "status", "token_usage"}
        self.messages: dict[int, list] = {}        # session_id -> graph-session-messages results
        self.users: dict[str, dict] = {}           # jwt -> introspect answer
        self.permissions: dict[tuple[str, int], object] = {}  # (jwt, org_id) -> "*" | {"chats": [...]}
        self.stopped: list[int] = []
        self.next_session_id = 100
        self.run_session_response: tuple[int, dict] | None = None  # force a status/body
        # Start the session, then time out before the answer: the outcome the chat cannot see.
        self.lose_run_session_response = False
        # An EpicStaff release from before introspection carried the user's display name.
        self.introspect_omits_display_name = False

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _org(self, request) -> int | None:
        raw = request.headers.get("X-Organization-Id")
        return int(raw) if raw else None

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        if request.headers.get("X-Api-Key") is None and not request.headers.get("Authorization", "").startswith("Bearer "):
            return httpx.Response(401, json={"detail": "Authentication credentials were not provided."})
        if method == "POST" and path == "/api/run-session/":
            if self.run_session_response:
                return httpx.Response(*self.run_session_response[:1], json=self.run_session_response[1])
            body = json.loads(request.content)
            if body["graph_id"] not in self.graphs:
                return httpx.Response(404, json={"status_code": 404, "code": "graph_not_found", "message": "Provided graph does not exist"})
            session_id, self.next_session_id = self.next_session_id, self.next_session_id + 1
            self.sessions[session_id] = {"org_id": self.graphs[body["graph_id"]]["org_id"], "status": "run", "token_usage": {}, "body": body}
            if self.lose_run_session_response:
                raise httpx.ReadTimeout("run-session answer lost", request=request)
            return httpx.Response(201, json={"session_id": session_id})
        if match := re.fullmatch(r"/api/sessions/(\d+)/stop/", path):
            session_id = int(match.group(1))
            if session_id not in self.sessions:
                return httpx.Response(404, json={"code": "session_not_found"})
            self.stopped.append(session_id)
            return httpx.Response(204)
        if match := re.fullmatch(r"/api/sessions/(\d+)/", path):
            session = self.sessions.get(int(match.group(1)))
            if session is None or session["org_id"] != self._org(request):
                return httpx.Response(404, json={"code": "session_not_found"})
            return httpx.Response(200, json={"id": int(match.group(1)), "status": session["status"], "token_usage": session["token_usage"]})
        if path == "/api/graph-session-messages/":
            session_id = int(request.url.params["session_id"])
            session = self.sessions.get(session_id)
            if session is None or session["org_id"] != self._org(request):
                return httpx.Response(404, json={"code": "not_found"})
            limit, offset = int(request.url.params.get("limit", 100)), int(request.url.params.get("offset", 0))
            results = self.messages.get(session_id, [])
            more = offset + limit < len(results)
            return httpx.Response(200, json={"count": len(results), "next": "more" if more else None, "previous": None, "results": results[offset : offset + limit]})
        if match := re.fullmatch(r"/api/graphs/(\d+)/", path):
            if request.headers.get("Authorization", "").startswith("Bearer "):
                # Like HasOrgPermission: authentication, then membership and flows:read, before the lookup.
                token = request.headers["Authorization"].removeprefix("Bearer ")
                if not self.users.get(token, {}).get("active"):
                    return httpx.Response(401, json={"detail": "Given token not valid for any token type"})
                answer = self.permissions.get((token, self._org(request)))
                if answer is None or (answer != "*" and "read" not in answer.get("flows", [])):
                    return httpx.Response(403, json={"status_code": 403, "code": "forbidden", "message": "You do not have permission to retrieve flows."})
            graph = self.graphs.get(int(match.group(1)))
            if graph is None or graph["org_id"] != self._org(request):
                return httpx.Response(404, json={"code": "not_found"})
            return httpx.Response(200, json={
                "id": int(match.group(1)),
                "start_node_list": [{"variables": graph["start_variables"]}] if graph.get("start_variables") is not None else [],
                "end_node_list": [{"output_map": graph["output_map"]}] if graph.get("output_map") is not None else [],
            })
        if method == "POST" and path == "/api/auth/introspect/":
            token = json.loads(request.content)["token"]
            answer = dict(self.users.get(token, {"active": False}))
            if self.introspect_omits_display_name:
                answer.pop("display_name", None)
            elif answer.get("active"):
                # Like EpicStaff: the stored name, else one derived from the email.
                answer.setdefault("display_name", answer["email"].split("@")[0])
            return httpx.Response(200, json=answer)
        if path == "/api/permissions/me/":
            token = request.headers["Authorization"].removeprefix("Bearer ")
            answer = self.permissions.get((token, self._org(request)))
            if answer is None:
                return httpx.Response(403, json={"status_code": 403, "code": "forbidden", "message": "Not a member"})
            return httpx.Response(200, json={"org_id": self._org(request), "is_superadmin": answer == "*", "role": None, "permissions": answer})
        return httpx.Response(404, json={"code": "unknown_route", "message": path})
