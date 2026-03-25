"""Shared API helpers, constants, and utilities for epicstaff_tools."""

import sys
import os
import re
import json
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

_SKILL_DIR = Path(__file__).resolve().parent
_REPO_ROOT = Path(__file__).resolve().parents[3]

def _load_env():
    """Load key=value pairs from .env. Checks skill dir first, then src/.env."""
    env = {}
    candidates = [
        _SKILL_DIR / ".env",
        _REPO_ROOT / "src" / ".env",
    ]
    for env_file in candidates:
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    key = k.strip()
                    if key not in env:
                        env[key] = v.strip()
    return env

_env = _load_env()

_DJANGO_PORT = os.environ.get("DJANGO_PORT", _env.get("DJANGO_PORT", "8000"))
_INSIDE_CONTAINER = os.path.exists("/.dockerenv")
_DEFAULT_API_URL = f"http://django_app:{_DJANGO_PORT}/api" if _INSIDE_CONTAINER else f"http://localhost:{_DJANGO_PORT}/api"
BASE_URL = os.environ.get("API_BASE_URL", _env.get("API_BASE_URL", _DEFAULT_API_URL))
_API_HOST_HEADER = {"Host": "localhost"} if "django_app" in BASE_URL else {}
REPO_ROOT = _REPO_ROOT
_MY_EPICSTAFF = REPO_ROOT / ".my_epicstaff"
FLOWS_DIR = _MY_EPICSTAFF / "flows"
TOOLS_DIR = _MY_EPICSTAFF / "tools"
PROJECTS_DIR = _MY_EPICSTAFF / "projects"

READ_ONLY_COMMANDS = {
    "list", "get", "nodes", "edges", "connections", "route-map",
    "cdt", "cdt-code", "cdt-prompts",
    "sessions", "session", "session-inspect", "session-timings", "vars", "history", "trace", "crew-input",
    "crews", "agents", "tools", "tool",
    "oc-status", "oc-sessions", "oc-messages", "oc-session",
    "verify", "export-compare",
    "test-flow",
}


def _set_base_url(url):
    global BASE_URL
    BASE_URL = url


# ═══════════════════════════════════════════════════════════════════════════
# API helpers
# ═══════════════════════════════════════════════════════════════════════════

def _rewrite_pagination_url(next_url):
    """Rewrite Django pagination URLs to use the actual BASE_URL origin.

    Django generates 'next'/'previous' URLs from the Host header, which may
    point to localhost — unreachable from inside a container.  Replace the
    scheme+host+port+base-path prefix with BASE_URL so the request reaches
    the correct backend.
    """
    from urllib.parse import urlparse
    parsed = urlparse(next_url)
    base_parsed = urlparse(BASE_URL)
    # Strip the BASE_URL path prefix (e.g. "/api") from the next_url path
    # so we can prepend BASE_URL cleanly.
    api_prefix = base_parsed.path.rstrip("/")
    rel = parsed.path
    if api_prefix and rel.startswith(api_prefix):
        rel = rel[len(api_prefix):]
    qs = f"?{parsed.query}" if parsed.query else ""
    return f"{BASE_URL}/{rel.lstrip('/')}{qs}"


def api_get(path, params=None):
    url = f"{BASE_URL}/{path.lstrip('/')}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        if qs:
            url += f"?{qs}"
    req = urllib.request.Request(url, headers=_API_HOST_HEADER)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    results = data.get("results", data) if isinstance(data, dict) and "results" in data else data
    if isinstance(data, dict) and data.get("next"):
        while data.get("next"):
            nreq = urllib.request.Request(_rewrite_pagination_url(data["next"]), headers=_API_HOST_HEADER)
            with urllib.request.urlopen(nreq) as resp:
                data = json.loads(resp.read())
            results.extend(data.get("results", []))
    return results


def api_get_page(path, params=None):
    """Like api_get but returns only the first page (no pagination follow).
    Use when you only need a small number of results and don't want to
    fetch all pages (e.g. 'limit=2' should return 2, not all results)."""
    url = f"{BASE_URL}/{path.lstrip('/')}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        if qs:
            url += f"?{qs}"
    req = urllib.request.Request(url, headers=_API_HOST_HEADER)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return data.get("results", data) if isinstance(data, dict) and "results" in data else data


def api_patch(path, payload):
    url = f"{BASE_URL}/{path.lstrip('/')}"
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="PATCH",
                                headers={"Content-Type": "application/json", **_API_HOST_HEADER})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def api_post(path, payload):
    url = f"{BASE_URL}/{path.lstrip('/')}"
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                headers={"Content-Type": "application/json", **_API_HOST_HEADER})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def api_delete(path):
    url = f"{BASE_URL}/{path.lstrip('/')}"
    req = urllib.request.Request(url, method="DELETE", headers=_API_HOST_HEADER)
    urllib.request.urlopen(req)


# ═══════════════════════════════════════════════════════════════════════════
# Graph / node helpers
# ═══════════════════════════════════════════════════════════════════════════

def _get_graph(graph_id):
    return api_get(f"/graphs/{graph_id}/")


def _get_cdt_nodes(graph_id):
    data = api_get("/classification-decision-table-node/", {"graph": graph_id})
    return data if isinstance(data, list) else data


def _get_pn_nodes(graph_id):
    data = api_get("/pythonnodes/", {"graph": graph_id})
    return data if isinstance(data, list) else data


def _get_wh_nodes(graph_id):
    data = api_get("/webhook-trigger-nodes/", {"graph": graph_id})
    return data if isinstance(data, list) else data


def _flows_dir(graph_id):
    d = FLOWS_DIR / str(graph_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


# All node-list keys in the graph API response
_NODE_LIST_KEYS = [
    "start_node_list", "end_node_list", "python_node_list",
    "crew_node_list", "llm_node_list", "code_agent_node_list",
    "file_extractor_node_list", "audio_transcription_node_list",
    "webhook_trigger_node_list", "telegram_trigger_node_list",
    "classification_decision_table_node_list", "decision_table_node_list",
    "note_node_list", "subgraph_node_list",
]


def build_name_to_id_map(graph):
    """Build {node_name: db_id} from all node lists in a graph response."""
    m = {}
    for key in _NODE_LIST_KEYS:
        for n in graph.get(key, []):
            name = n.get("node_name")
            if name:
                m[name] = n["id"]
    return m


def build_id_to_name_map(graph):
    """Build {db_id: node_name} from all node lists in a graph response."""
    m = {}
    for key in _NODE_LIST_KEYS:
        for n in graph.get(key, []):
            m[n["id"]] = n.get("node_name", f"node#{n['id']}")
    return m


def resolve_node_id(name, graph):
    """Resolve a node name (or integer string) to a DB ID.

    Accepts exact node_name (e.g. "Python-Node (#3)"), the special
    names "__start__" / "__end__", or a raw integer ID string.
    Returns int or raises SystemExit on failure.
    """
    # Raw integer
    try:
        return int(name)
    except (ValueError, TypeError):
        pass
    m = build_name_to_id_map(graph)
    if name in m:
        return m[name]
    # Fuzzy match: case-insensitive substring
    norm = _normalize_slug(name)
    for node_name, nid in m.items():
        if norm == _normalize_slug(node_name):
            return nid
        if norm in _normalize_slug(node_name):
            return nid
    print(f"Node '{name}' not found in flow. Available: {', '.join(sorted(m.keys()))}", file=sys.stderr)
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════
# Slug / file parsing helpers
# ═══════════════════════════════════════════════════════════════════════════

def _normalize_slug(slug):
    return re.sub(r"[-_\s]+", "_", slug.lower()).strip("_")


SLUG_TO_CDT_NAME = {}
SLUG_TO_PN_NAME = {}
SLUG_TO_WH_NAME = {}


def _match_node(slug, nodes, slug_map):
    norm = _normalize_slug(slug)
    if norm in slug_map:
        target = slug_map[norm]
        for n in nodes:
            if n.get("node_name") == target:
                return n
    for n in nodes:
        nn = _normalize_slug(
            n.get("node_name", "").replace("(", "").replace(")", "")
            .replace("#", "").replace("  ", " "))
        if nn == norm or norm in nn or nn in norm:
            return n
    return None


CG_SEMANTIC_FIELDS = {
    "order", "group_name", "expression", "prompt_id", "manipulation",
    "continue_flag", "route_code", "dock_visible",
    "field_expressions", "field_manipulations",
}
CG_META_RENAMES = {"continue": "continue_flag"}


def _canonicalize_groups(groups):
    result = []
    for g in (groups or []):
        canon = {}
        for k, v in g.items():
            key = CG_META_RENAMES.get(k, k)
            if key in CG_SEMANTIC_FIELDS:
                canon[key] = v
        for f in CG_SEMANTIC_FIELDS:
            if f not in canon:
                canon[f] = None if f not in ("field_expressions", "field_manipulations") else {}
        result.append(canon)
    result.sort(key=lambda g: g.get("order", 0))
    return result


def _canonicalize_code(code):
    return (code or "").strip()


def _canonical_json(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def _canonicalize_prompts(prompts):
    if isinstance(prompts, list):
        d = {}
        for p in list(prompts):
            p = dict(p)
            pid = p.pop("prompt_id", f"prompt_{len(d)}")
            d[pid] = p
        prompts = d
    return prompts or {}


class FileSpec:
    def __init__(self, path, kind, slug, field):
        self.path = path
        self.kind = kind
        self.slug = slug
        self.field = field

    def __repr__(self):
        return f"FileSpec({self.kind}/{self.slug}/{self.field})"


def _parse_file(filepath):
    name = Path(filepath).stem
    ext = Path(filepath).suffix
    m = re.match(r"^cdt_(.+?)_(pre|post)$", name)
    if m and ext == ".py":
        return FileSpec(filepath, "cdt", m.group(1), f"{m.group(2)}_computation_code")
    m = re.match(r"^cdt_(.+?)_groups$", name)
    if m and ext == ".json":
        return FileSpec(filepath, "cdt", m.group(1), "condition_groups")
    m = re.match(r"^cdt_(.+?)_prompts$", name)
    if m and ext == ".json":
        return FileSpec(filepath, "cdt", m.group(1), "prompts")
    m = re.match(r"^node_(.+)$", name)
    if m and ext == ".py":
        return FileSpec(filepath, "python", m.group(1), "code")
    m = re.match(r"^webhook_(.+)$", name)
    if m and ext == ".py":
        return FileSpec(filepath, "webhook", m.group(1), "code")
    return None


def _discover_files(path):
    p = Path(path)
    if p.is_file():
        spec = _parse_file(str(p))
        return [spec] if spec else []
    if p.is_dir():
        specs = []
        for f in sorted(p.iterdir()):
            if f.is_file() and not f.name.startswith("_"):
                spec = _parse_file(str(f))
                if spec:
                    specs.append(spec)
        return specs
    return []


def _find_meta_cdt(graph_id, node_name):
    graph = _get_graph(graph_id)
    for n in graph.get("metadata", {}).get("nodes", []):
        nn = n.get("node_name", n.get("data", {}).get("name", ""))
        if nn == node_name and "table" in n.get("data", {}):
            return n["data"]["table"]
    return None


def _read_from_file(spec):
    with open(spec.path) as f:
        raw = f.read()
    if spec.field == "condition_groups":
        return _canonicalize_groups(json.loads(raw))
    elif spec.field == "prompts":
        return _canonicalize_prompts(json.loads(raw))
    return _canonicalize_code(raw)


def _read_from_db(spec, graph_id):
    if spec.kind == "cdt":
        node = _match_node(spec.slug, _get_cdt_nodes(graph_id), SLUG_TO_CDT_NAME)
        if not node:
            return None, None
        name = node["node_name"]
        if spec.field == "condition_groups":
            return _canonicalize_groups(node.get("condition_groups", [])), name
        elif spec.field == "prompts":
            return _canonicalize_prompts(node.get("prompts", {})), name
        return _canonicalize_code(node.get(spec.field, "")), name
    elif spec.kind == "python":
        node = _match_node(spec.slug, _get_pn_nodes(graph_id), SLUG_TO_PN_NAME)
        if not node:
            return None, None
        name = node.get("node_name", "?")
        pc = node.get("python_code", {})
        code = pc.get("code", "") if isinstance(pc, dict) else ""
        return _canonicalize_code(code), name
    elif spec.kind == "webhook":
        node = _match_node(spec.slug, _get_wh_nodes(graph_id), SLUG_TO_WH_NAME)
        if not node:
            return None, None
        name = node.get("node_name", "?")
        pc = node.get("python_code", {})
        code = pc.get("code", "") if isinstance(pc, dict) else ""
        return _canonicalize_code(code), name
    return None, None


def _read_from_metadata(spec, graph_id, node_name):
    if spec.kind == "cdt":
        table = _find_meta_cdt(graph_id, node_name)
        if not table:
            return None
        if spec.field == "condition_groups":
            return _canonicalize_groups(table.get("condition_groups", []))
        elif spec.field == "prompts":
            return _canonicalize_prompts(table.get("prompts", {}))
        elif spec.field == "pre_computation_code":
            return _canonicalize_code(table.get("pre_computation", {}).get("code", ""))
        elif spec.field == "post_computation_code":
            return _canonicalize_code(table.get("post_computation", {}).get("code", ""))
    elif spec.kind == "python":
        graph = _get_graph(graph_id)
        for n in graph.get("metadata", {}).get("nodes", []):
            nn = n.get("node_name", n.get("data", {}).get("name", ""))
            if nn == node_name and n.get("type", "").startswith("python"):
                return _canonicalize_code(n.get("data", {}).get("code", ""))
    elif spec.kind == "webhook":
        graph = _get_graph(graph_id)
        for n in graph.get("metadata", {}).get("nodes", []):
            nn = n.get("node_name", n.get("data", {}).get("name", ""))
            if nn == node_name and "webhook" in n.get("type", ""):
                return _canonicalize_code(n.get("data", {}).get("code", ""))
    return None


def _read_value(args):
    if getattr(args, "value_file", None):
        with open(args.value_file, "r") as f:
            return f.read()
    if getattr(args, "value", None):
        return args.value
    print("Provide --value or --value-file", file=sys.stderr)
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════
# OpenCode helpers
# ═══════════════════════════════════════════════════════════════════════════

OPENCODE_CONTAINER = "sandbox"
OPENCODE_PORT = int(os.environ.get("OPENCODE_PORT", _env.get("OPENCODE_PORT", "4096")))

def _is_inside_container():
    """Detect if we're running inside a Docker container."""
    return os.path.exists("/.dockerenv") or os.environ.get("API_BASE_URL")


def _oc_curl(path, method="GET", timeout=10):
    """Reach OpenCode — direct HTTP if inside container, docker exec from host."""
    url = f"http://localhost:{OPENCODE_PORT}{path}"
    if _is_inside_container():
        import urllib.request
        try:
            req = urllib.request.Request(url, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            return json.loads(raw) if raw.strip() else None
        except Exception as e:
            print(f"  Error reaching OpenCode: {e}", file=sys.stderr)
            return None
    else:
        import subprocess
        cmd = ["docker", "exec", OPENCODE_CONTAINER, "curl", "-s", "-X", method, url]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if result.returncode != 0:
                return None
            return json.loads(result.stdout) if result.stdout.strip() else None
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
            print(f"  Error reaching OpenCode: {e}", file=sys.stderr)
            return None


# ═══════════════════════════════════════════════════════════════════════════
# Tool slug helper
# ═══════════════════════════════════════════════════════════════════════════

def _tool_slug(name):
    return _normalize_slug(re.sub(r"\s*\(\d+\)\s*$", "", name))


def _get_flow_tool_ids(graph_id):
    """Return set of tool IDs used by agents in this flow's crews."""
    graph = api_get(f"/graphs/{graph_id}/")
    ids = set()
    for cn in graph.get("crew_node_list", []):
        c = cn.get("crew", {})
        if isinstance(c, dict):
            for aid in c.get("agents", []):
                try:
                    agent = api_get(f"/agents/{aid}/")
                    for t in agent.get("tools", []):
                        if isinstance(t, dict):
                            ids.add(t.get("data", t).get("id"))
                except Exception:
                    pass
    return ids
