"""An in-memory stand-in for the EpicStaff API endpoints the Weather sample calls.

Serves an `httpx.MockTransport`. It keeps one organization's flows, files, secrets, LLM
configs and sessions, records every request, and answers in EpicStaff's shapes (DRF
limit/offset pages, the `{status_code, code, message}` error envelope).

A flow's bulk save works as EpicStaff's does: a node without an `id` is added and gets one, a
node with an `id` replaces that node whole, and nodes the save does not name stay.
"""

import json
import re
from dataclasses import dataclass, field

import httpx


def _error(status, code, message):
    return httpx.Response(status, json={"status_code": status, "code": code, "message": message})


@dataclass
class Recorded:
    method: str
    path: str
    params: dict
    headers: httpx.Headers
    body: object


@dataclass
class FakeEpicStaff:
    org_id: int = 3
    graphs: dict = field(default_factory=dict)
    files: dict = field(default_factory=dict)
    secrets: dict = field(default_factory=dict)
    llm_configs: dict = field(default_factory=dict)
    llm_models: dict = field(default_factory=lambda: {index: f"model-{index}" for index in range(1, 251)})
    sessions: dict = field(default_factory=dict)
    people: dict = field(default_factory=dict)
    refusals: dict = field(default_factory=dict)
    requests: list = field(default_factory=list)
    _next_id: int = 100
    # Nodes count apart, so a flow's nodes never shift the ids of what a test creates next.
    _next_node_id: int = 1000

    def transport(self):
        return httpx.MockTransport(self)

    def writes(self):
        return [request for request in self.requests if request.method not in ("GET", "HEAD")]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/")
        try:
            body = json.loads(request.content) if request.content and "json" in request.headers.get("content-type", "") else request.content
        except ValueError:
            body = request.content
        self.requests.append(Recorded(request.method, path, dict(request.url.params), request.headers, body))
        if request.headers.get("x-organization-id") != str(self.org_id):
            return _error(404, "organization_not_found", "Organization not found.")
        refusal = self.refusals.get((request.method, path))
        if refusal is not None:
            return _error(*refusal)
        for (method, pattern), handler in self._routes():
            match = re.fullmatch(pattern, path)
            if method == request.method and match:
                return handler(request, body, *match.groups())
        return _error(404, "not_found", "Not found.")

    def _routes(self):
        return [
            (("GET", r"graph-light/"), self._list_graphs),
            (("POST", r"graphs/"), self._create_graph),
            (("GET", r"graphs/(\d+)/"), self._get_graph),
            (("PATCH", r"graphs/(\d+)/"), self._patch_graph),
            (("POST", r"graphs/(\d+)/save/"), self._save_graph),
            (("GET", r"storage/info/"), self._file_info),
            (("POST", r"storage/upload/stream"), self._upload),
            (("POST", r"run-session/"), self._run_session),
            (("GET", r"sessions/(\d+)/"), self._get_session),
            (("GET", r"llm-configs/"), self._list_llm_configs),
            (("POST", r"llm-configs/"), self._create_llm_config),
            (("GET", r"llm-models/"), self._list_llm_models),
            (("GET", r"llm-models/(\d+)/"), self._get_llm_model),
            (("GET", r"secrets/"), self._list_secrets),
            (("POST", r"secrets/"), self._create_secret),
            (("GET", r"plugin-runtime/people/(\d+)/"), self._get_person),
        ]

    def _new_id(self):
        self._next_id += 1
        return self._next_id

    @staticmethod
    def _page(items, request):
        limit = int(request.url.params.get("limit", 50))
        offset = int(request.url.params.get("offset", 0))
        page = items[offset : offset + limit]
        more = offset + limit < len(items)
        return httpx.Response(
            200,
            json={"count": len(items), "next": "http://next" if more else None, "previous": None, "results": page},
        )

    def add_graph(self, name, description="", contents=None):
        """A flow someone else made; returns its id."""
        graph_id = self._new_id()
        self.graphs[graph_id] = {"name": name, "description": description, "save_version": 1, "contents": contents}
        return graph_id

    def _list_graphs(self, request, body):
        # EpicStaff's search: the text in the name or the description, case-insensitively.
        search = request.url.params.get("search", "").lower()
        found = [
            {"id": graph_id, "name": graph["name"], "description": graph["description"]}
            for graph_id, graph in sorted(self.graphs.items(), reverse=True)
            if search in graph["name"].lower() or search in graph["description"].lower()
        ]
        return self._page(found, request)

    def _create_graph(self, request, body):
        if any(graph["name"] == body["name"] for graph in self.graphs.values()):
            return _error(400, "invalid", "name: A flow with this name already exists.")
        graph_id = self._new_id()
        self.graphs[graph_id] = {"name": body["name"], "description": body.get("description", ""), "save_version": 1, "contents": None}
        return httpx.Response(201, json={"id": graph_id, "name": body["name"]})

    def _get_graph(self, request, body, graph_id):
        graph = self.graphs.get(int(graph_id))
        if graph is None:
            return _error(404, "not_found", "Not found.")
        contents = graph["contents"] or {}
        return httpx.Response(
            200,
            json={
                "id": int(graph_id),
                "name": graph["name"],
                "description": graph["description"],
                "save_version": graph["save_version"],
                "python_node_list": contents.get("python_node_list", []),
            },
        )

    def _patch_graph(self, request, body, graph_id):
        graph = self.graphs.get(int(graph_id))
        if graph is None:
            return _error(404, "not_found", "Not found.")
        for name in ("name", "description"):
            if name in body:
                graph[name] = body[name]
        return httpx.Response(200, json={"id": int(graph_id), "name": graph["name"], "description": graph["description"]})

    def _save_graph(self, request, body, graph_id):
        graph = self.graphs[int(graph_id)]
        if body["save_version"] != graph["save_version"]:
            return _error(409, "conflict", "The flow was saved meanwhile.")
        contents = graph["contents"] or {}
        node_lists = {key: items for key, items in body.items() if key.endswith("_node_list")}
        for key, items in node_lists.items():
            known = {node["id"] for node in contents.get(key, [])}
            missing = [item["id"] for item in items if item.get("id") is not None and item["id"] not in known]
            if missing:
                return _error(400, "invalid", f"{key}: id={missing[0]} not found in graph {graph_id}")
        for key, items in node_lists.items():
            nodes = contents.setdefault(key, [])
            for item in items:
                if item.get("id") is None:
                    self._next_node_id += 1
                    nodes.append({**item, "id": self._next_node_id})
                else:
                    nodes[[node["id"] for node in nodes].index(item["id"])] = dict(item)
        contents.setdefault("edge_list", []).extend(body.get("edge_list", []))
        graph["contents"] = contents
        graph["save_version"] += 1
        return httpx.Response(200, json={"id": int(graph_id)})

    def _file_info(self, request, body):
        path = request.url.params["path"]
        if path not in self.files:
            return _error(404, "not_found", f"File does not exist: {path}")
        return httpx.Response(200, json={"path": path, "size": len(self.files[path])})

    def _upload(self, request, body):
        path = f"{request.url.params['path']}/{request.url.params['filename']}"
        self.files[path] = request.content
        return httpx.Response(200, json={"status": "DONE", "path": path})

    def _run_session(self, request, body):
        session_id = self._new_id()
        self.sessions[session_id] = {"id": session_id, "status": "pending", "status_data": {}, "graph": body["graph_id"], "variables": body["variables"]}
        return httpx.Response(201, json={"session_id": session_id})

    def _get_session(self, request, body, session_id):
        session = self.sessions.get(int(session_id))
        if session is None:
            return _error(404, "not_found", "Not found.")
        return httpx.Response(200, json=session)

    def _list_llm_configs(self, request, body):
        name = request.url.params.get("custom_name")
        found = [
            {"id": config_id, **config}
            for config_id, config in sorted(self.llm_configs.items())
            if name is None or config["custom_name"] == name
        ]
        return self._page(found, request)

    def _create_llm_config(self, request, body):
        if body["api_key_secret_id"] not in self.secrets:
            return _error(400, "invalid", "api_key_secret_id: Invalid pk.")
        config_id = self._new_id()
        self.llm_configs[config_id] = {"custom_name": body["custom_name"], "model": body["model"], "api_key_secret_id": body["api_key_secret_id"]}
        return httpx.Response(201, json={"id": config_id, **self.llm_configs[config_id]})

    def _list_llm_models(self, request, body):
        return self._page([{"id": model_id, "name": name} for model_id, name in sorted(self.llm_models.items())], request)

    def _get_llm_model(self, request, body, model_id):
        if int(model_id) not in self.llm_models:
            return _error(404, "not_found", "Not found.")
        return httpx.Response(200, json={"id": int(model_id), "name": self.llm_models[int(model_id)]})

    def add_secret(self, name, value):
        """A Secret that is already there; returns its id."""
        secret_id = self._new_id()
        self.secrets[secret_id] = {"name": name, "value": value}
        return secret_id

    def _list_secrets(self, request, body):
        # EpicStaff shows the last four characters of a value of nine or more, never the value.
        listed = [
            {"id": secret_id, "name": secret["name"], "tail": secret["value"][-4:] if len(secret["value"]) >= 9 else ""}
            for secret_id, secret in sorted(self.secrets.items())
        ]
        return self._page(listed, request)

    def _create_secret(self, request, body):
        if any(secret["name"] == body["name"] for secret in self.secrets.values()):
            return _error(400, "invalid", "A secret with this name already exists in this organization.")
        secret_id = self._new_id()
        self.secrets[secret_id] = {"name": body["name"], "value": body["value"]}
        return httpx.Response(201, json={"id": secret_id, "name": body["name"]})

    def _get_person(self, request, body, user_id):
        person = self.people.get(int(user_id))
        if person is None:
            return _error(404, "person_not_found", "No such person.")
        return httpx.Response(200, json=person)
