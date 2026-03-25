"""Flow write operations: push, pull, patch, sync, rename, and OpenCode abort."""

import json
import sys
import time
from pathlib import Path

from common import (
    api_get, api_post, api_patch, _get_graph, _get_cdt_nodes, _get_pn_nodes, _get_wh_nodes,
    _flows_dir, _normalize_slug, _match_node, _discover_files,
    _read_value, _oc_curl,
    SLUG_TO_CDT_NAME, SLUG_TO_PN_NAME, SLUG_TO_WH_NAME,
)


# ═══════════════════════════════════════════════════════════════════════════
# Push / Pull
# ═══════════════════════════════════════════════════════════════════════════

def _push_cdt(spec, content, graph_id):
    node = _match_node(spec.slug, _get_cdt_nodes(graph_id), SLUG_TO_CDT_NAME)
    if not node:
        print(f"  ❌ {Path(spec.path).name}: CDT not found for slug '{spec.slug}'")
        return False
    node_id, node_name = node["id"], node["node_name"]
    if spec.field == "condition_groups":
        clean = [{k: v for k, v in g.items()
                  if k not in ("id", "classification_decision_table_node")} for g in content]
        db_payload = {"condition_groups": clean}
    elif spec.field == "prompts":
        if isinstance(content, list):
            d = {}
            for p in content:
                p = dict(p)
                pid = p.pop("prompt_id", p.pop("id", f"prompt_{len(d)}"))
                d[pid] = p
            content = d
        db_payload = {"prompts": content}
    else:
        db_payload = {spec.field: content}
    api_patch(f"/classification-decision-table-node/{node_id}/", db_payload)
    print(f"  ✅ {Path(spec.path).name} → CDT '{node_name}' .{spec.field}  [DB]")
    return True


def _push_python(spec, content, graph_id):
    node = _match_node(spec.slug, _get_pn_nodes(graph_id), SLUG_TO_PN_NAME)
    if not node:
        print(f"  ❌ {Path(spec.path).name}: Python node not found for slug '{spec.slug}'")
        return False
    node_id = node["id"]
    node_name = node.get("node_name", "?")
    libs = (node.get("python_code", {}) or {}).get("libraries", "")
    if "def main(" not in content:
        print(f"  ⚠️  {Path(spec.path).name}: no 'def main(...)' — Python nodes require a main() entrypoint")
    api_patch(f"/pythonnodes/{node_id}/", {"python_code": {"code": content, "libraries": libs}})
    print(f"  ✅ {Path(spec.path).name} → Python '{node_name}'  [DB]")
    return True


def _push_webhook(spec, content, graph_id):
    node = _match_node(spec.slug, _get_wh_nodes(graph_id), SLUG_TO_WH_NAME)
    if not node:
        print(f"  ❌ {Path(spec.path).name}: Webhook node not found for slug '{spec.slug}'")
        return False
    node_id = node["id"]
    node_name = node.get("node_name", "?")
    libs = (node.get("python_code", {}) or {}).get("libraries", [])
    if "def main(" not in content:
        print(f"  ⚠️  {Path(spec.path).name}: no 'def main(...)' — Webhook nodes require a main() entrypoint")
    api_patch(f"/webhook-trigger-nodes/{node_id}/", {"python_code": {"code": content, "libraries": libs}})
    print(f"  ✅ {Path(spec.path).name} → Webhook '{node_name}'  [DB]")
    return True


def cmd_push(args):
    """Push file(s) to DB."""
    if not args.path:
        args.path = str(_flows_dir(args.graph_id))
    specs = _discover_files(args.path)
    if not specs:
        print(f"No recognized files in: {args.path}")
        sys.exit(1)
    print(f"Pushing {len(specs)} file(s) to flow {args.graph_id}:\n")
    ok, fail = 0, 0
    for spec in specs:
        try:
            with open(spec.path) as f:
                raw = f.read()
            content = json.loads(raw) if spec.field in ("condition_groups", "prompts") else raw
            if spec.kind == "cdt":
                success = _push_cdt(spec, content, args.graph_id)
            elif spec.kind == "webhook":
                success = _push_webhook(spec, content, args.graph_id)
            else:
                success = _push_python(spec, content, args.graph_id)
            if success:
                ok += 1
            else:
                fail += 1
        except Exception as e:
            print(f"  ❌ {Path(spec.path).name}: {e}")
            fail += 1
    print(f"\nDone: {ok} pushed, {fail} failed.")
    if fail:
        sys.exit(1)


def cmd_pull(args):
    """Pull DB state into local files.

    Uses the graph's embedded node lists (python_node_list, etc.) rather than
    separate API endpoints, which can return cross-graph nodes.
    """
    outdir = Path(args.path) if args.path else _flows_dir(args.graph_id)
    outdir.mkdir(parents=True, exist_ok=True)
    graph = _get_graph(args.graph_id)
    cdts = graph.get("classification_decision_table_node_list", [])
    pns = graph.get("python_node_list", [])
    whs = graph.get("webhook_trigger_node_list", [])
    count = 0
    print(f"Pulling from flow {args.graph_id} into {outdir}/\n")
    for node in cdts:
        name = node["node_name"]
        slug = _normalize_slug(name.replace("(", "").replace(")", "").replace("#", "").replace("  ", " "))
        for stage in ("pre", "post"):
            code = node.get(f"{stage}_computation_code") or ""
            if code.strip():
                p = outdir / f"cdt_{slug}_{stage}.py"
                p.write_text(code)
                print(f"  {p.name} ({len(code)} chars)")
                count += 1
        groups = node.get("condition_groups", [])
        if groups:
            p = outdir / f"cdt_{slug}_groups.json"
            clean = [{k: v for k, v in g.items()
                      if k not in ("id", "classification_decision_table_node")} for g in groups]
            p.write_text(json.dumps(clean, indent=2))
            print(f"  {p.name} ({len(groups)} groups)")
            count += 1
        prompts = node.get("prompts", {})
        if prompts:
            p = outdir / f"cdt_{slug}_prompts.json"
            p.write_text(json.dumps(prompts, indent=2))
            print(f"  {p.name} ({len(prompts)} prompts)")
            count += 1
    for node in pns:
        name = node.get("node_name", "?")
        slug = _normalize_slug(name.replace("(", "").replace(")", "").replace("#", "").replace("  ", " "))
        pc = node.get("python_code", {})
        code = pc.get("code", "") if isinstance(pc, dict) else ""
        if code.strip():
            p = outdir / f"node_{slug}.py"
            p.write_text(code)
            print(f"  {p.name} ({len(code)} chars)")
            count += 1
    for node in whs:
        name = node.get("node_name", "?")
        slug = _normalize_slug(name.replace("(", "").replace(")", "").replace("#", "").replace("  ", " "))
        pc = node.get("python_code", {})
        code = pc.get("code", "") if isinstance(pc, dict) else ""
        if code.strip():
            p = outdir / f"webhook_{slug}.py"
            p.write_text(code)
            print(f"  {p.name} ({len(code)} chars)")
            count += 1
    print(f"\nPulled {count} files.")


# ═══════════════════════════════════════════════════════════════════════════
# Patching
# ═══════════════════════════════════════════════════════════════════════════

def cmd_patch_cdt(args):
    """Patch a CDT field in DB."""
    node_name = args.node_name
    field = args.field
    graph_id = args.graph_id
    value = _read_value(args)
    try:
        value = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        pass
    cdts = _get_cdt_nodes(graph_id)
    matches = [c for c in cdts if c["node_name"] == node_name]
    if not matches:
        print(f"Error: CDT '{node_name}' not found in flow {graph_id}.", file=sys.stderr)
        sys.exit(1)
    cdt_id = matches[0]["id"]
    print(f"PATCHing CDT '{node_name}' (id={cdt_id}), field='{field}'")
    result = api_patch(f"/classification-decision-table-node/{cdt_id}/", {field: value})
    print(f"  DB updated.")


def cmd_patch_python(args):
    """Patch Python node code in DB."""
    graph_id = args.graph_id
    node_name = args.node_name
    value = _read_value(args)
    graph = _get_graph(graph_id)
    py_nodes = graph.get("python_node_list", [])
    db_node = None
    for pn in py_nodes:
        if pn.get("node_name") == node_name:
            db_node = pn
            break
    if not db_node:
        print(f"Python node '{node_name}' not found in flow {graph_id}")
        sys.exit(1)
    node_id = db_node["id"]
    libs = (db_node.get("python_code", {}) or {}).get("libraries", "")
    print(f"PATCHing Python node '{node_name}' (id={node_id})")
    if "def main(" not in value:
        print(f"  ⚠️  WARNING: Code does not contain 'def main(...)'. Python nodes require a main() entrypoint.")
        print(f"     The crew executor calls main() with the node's input_map keys as keyword arguments.")
    api_patch(f"/pythonnodes/{node_id}/", {"python_code": {"code": value, "libraries": libs}})
    print(f"  DB updated.")


def cmd_patch_webhook(args):
    """Patch webhook node code in DB."""
    graph_id = args.graph_id
    node_name = args.node_name
    value = _read_value(args)
    graph = _get_graph(graph_id)
    wh_nodes = graph.get("webhook_trigger_node_list", [])
    db_node = None
    for wn in wh_nodes:
        if wn.get("node_name") == node_name:
            db_node = wn
            break
    if not db_node:
        print(f"Webhook node '{node_name}' not found in flow {graph_id}")
        sys.exit(1)
    node_id = db_node["id"]
    libs = (db_node.get("python_code", {}) or {}).get("libraries", [])
    print(f"PATCHing Webhook node '{node_name}' (id={node_id})")
    if "def main(" not in value:
        print(f"  ⚠️  WARNING: Code does not contain 'def main(...)'. Webhook nodes require a main() entrypoint.")
    api_patch(f"/webhook-trigger-nodes/{node_id}/", {"python_code": {"code": value, "libraries": libs}})
    print(f"  DB updated.")


def cmd_patch_code_agent(args):
    """Patch Code Agent node fields in DB."""
    graph_id = args.graph_id
    node_name = args.node_name
    graph = _get_graph(graph_id)
    ca_nodes = graph.get("code_agent_node_list", [])
    db_node = None
    for cn in ca_nodes:
        if cn.get("node_name") == node_name:
            db_node = cn
            break
    if not db_node:
        print(f"Code Agent node '{node_name}' not found in flow {graph_id}", file=sys.stderr)
        sys.exit(1)
    node_id = db_node["id"]

    # Build DB payload from provided flags
    db_payload = {}
    if getattr(args, "value", None) or getattr(args, "value_file", None):
        db_payload["stream_handler_code"] = _read_value(args)
    if getattr(args, "llm_config", None):
        db_payload["llm_config"] = int(args.llm_config)
    if getattr(args, "system_prompt", None):
        db_payload["system_prompt"] = args.system_prompt
    if getattr(args, "system_prompt_file", None):
        with open(args.system_prompt_file) as f:
            db_payload["system_prompt"] = f.read()
    if getattr(args, "input_map", None):
        db_payload["input_map"] = json.loads(args.input_map)
    if getattr(args, "output_variable_path", None):
        db_payload["output_variable_path"] = args.output_variable_path
    if getattr(args, "libraries", None):
        db_payload["libraries"] = [l.strip() for l in args.libraries.split(",") if l.strip()]
    if getattr(args, "session_id", None) is not None:
        db_payload["session_id"] = args.session_id
    if getattr(args, "output_schema_file", None):
        with open(args.output_schema_file) as f:
            db_payload["output_schema"] = json.load(f)
    if getattr(args, "agent_mode", None):
        db_payload["agent_mode"] = args.agent_mode

    if not db_payload:
        print("No fields to patch. Use --value, --llm-config, --system-prompt, --input-map, --output-variable-path, or --libraries.", file=sys.stderr)
        sys.exit(1)

    print(f"PATCHing Code Agent node '{node_name}' (id={node_id})")
    for k, v in db_payload.items():
        label = repr(v) if not isinstance(v, str) or len(v) < 80 else repr(v[:77] + "...")
        print(f"  {k} = {label}")
    api_patch(f"/code-agent-nodes/{node_id}/", db_payload)
    print(f"  DB updated.")


def cmd_patch_dt(args):
    """Patch Decision Table node fields in DB."""
    graph_id = args.graph_id
    node_name = args.node_name
    graph = _get_graph(graph_id)
    dt_nodes = graph.get("decision_table_node_list", [])
    db_node = None
    for dn in dt_nodes:
        if dn.get("node_name") == node_name:
            db_node = dn
            break
    if not db_node:
        print(f"Decision Table node '{node_name}' not found in flow {graph_id}", file=sys.stderr)
        sys.exit(1)
    node_id = db_node["id"]

    db_payload = {}
    if getattr(args, "groups", None):
        db_payload["condition_groups"] = json.loads(args.groups)
    elif getattr(args, "groups_file", None):
        with open(args.groups_file) as f:
            db_payload["condition_groups"] = json.loads(f.read())
    if "condition_groups" in db_payload:
        for g in db_payload["condition_groups"]:
            g.setdefault("conditions", [])
    if getattr(args, "default_next_node", None):
        db_payload["default_next_node"] = args.default_next_node
    if getattr(args, "error_node", None):
        db_payload["next_error_node"] = args.error_node

    if not db_payload:
        print("No fields to patch. Use --groups, --default-next-node, or --error-node.", file=sys.stderr)
        sys.exit(1)

    print(f"PATCHing Decision Table '{node_name}' (id={node_id})")
    if "condition_groups" in db_payload:
        print(f"  condition_groups: {len(db_payload['condition_groups'])} groups")
        for g in db_payload["condition_groups"]:
            print(f"    [{g.get('order','-')}] {g.get('group_name','?')} → {g.get('next_node','default')} | expr: {g.get('expression','')}")
    if "default_next_node" in db_payload:
        print(f"  default_next_node: {db_payload['default_next_node']}")
    if "next_error_node" in db_payload:
        print(f"  next_error_node: {db_payload['next_error_node']}")

    api_patch(f"/decision-table-node/{node_id}/", db_payload)
    print(f"  DB updated.")


def cmd_patch_libraries(args):
    """Patch libraries on a Python node in DB."""
    graph_id = args.graph_id
    node_name = args.node_name
    libs = [l.strip() for l in args.libraries.split(",") if l.strip()]
    graph = _get_graph(graph_id)
    py_nodes = graph.get("python_node_list", [])
    db_node = None
    for pn in py_nodes:
        if pn.get("node_name") == node_name:
            db_node = pn
            break
    if not db_node:
        print(f"Python node '{node_name}' not found in flow {graph_id}", file=sys.stderr)
        sys.exit(1)
    node_id = db_node["id"]
    code = (db_node.get("python_code", {}) or {}).get("code", "")
    api_patch(f"/pythonnodes/{node_id}/", {"python_code": {"code": code, "libraries": libs}})
    print(f"  DB node {node_id} libraries: {libs}")


def cmd_patch_node_meta(args):
    """Patch input_map / output_variable_path on a node in DB."""
    graph_id = args.graph_id
    node_name = args.node_name
    graph = _get_graph(graph_id)

    db_payload = {}
    if getattr(args, "input_map", None):
        parsed = json.loads(args.input_map)
        db_payload["input_map"] = parsed
        print(f"  input_map set: {parsed}")
    if getattr(args, "output_variable_path", None):
        db_payload["output_variable_path"] = args.output_variable_path
        print(f"  output_variable_path set: {args.output_variable_path}")

    if not db_payload:
        print("No fields to patch. Use --input-map or --output-variable-path.", file=sys.stderr)
        sys.exit(1)

    # Patch DB node — detect type from graph node lists
    node_type_endpoints = {
        "python_node_list": "/pythonnodes/",
        "crew_node_list": "/crew-nodes/",
        "code_agent_node_list": "/code-agent-nodes/",
        "llm_node_list": "/llmnodes/",
        "file_extractor_node_list": "/file-extractor-nodes/",
        "audio_transcription_node_list": "/audio-transcription-nodes/",
    }
    db_patched = False
    for list_key, endpoint in node_type_endpoints.items():
        for db_node in graph.get(list_key, []):
            if db_node.get("node_name") == node_name:
                node_id = db_node["id"]
                api_patch(f"{endpoint}{node_id}/", db_payload)
                print(f"  DB updated ({list_key.replace('_list','')}, id={node_id}).")
                db_patched = True
                break
        if db_patched:
            break
    if not db_patched:
        print(f"Node '{node_name}' not found in flow {graph_id}", file=sys.stderr)
        sys.exit(1)


def cmd_patch_start_vars(args):
    """Set start node variables (PATCH). Use --replace to overwrite entirely."""
    graph_id = args.graph_id
    graph = _get_graph(graph_id)
    start_nodes = graph.get("start_node_list", [])
    if not start_nodes:
        print(f"No start node in flow {graph_id}", file=sys.stderr)
        sys.exit(1)
    start = start_nodes[0]
    start_id = start["id"]
    new_vars = json.loads(args.variables)
    if getattr(args, "replace", False):
        final = {"$schema": "start"}
        final.update(new_vars)
    else:
        final = start.get("variables", {})
        final.update(new_vars)
    api_patch(f"/startnodes/{start_id}/", {"variables": final})
    print(f"Start node {start_id} variables updated{' (replaced)' if getattr(args, 'replace', False) else ''}.")
    for k, v in final.items():
        vtype = type(v).__name__
        vpreview = str(v)[:80] if not isinstance(v, dict) else f"{{...}} ({len(v)} keys)"
        print(f"  {k}: {vtype} = {vpreview}")


def cmd_rename_node(args):
    """Rename a node in DB. Edges use integer IDs, no edge update needed."""
    graph_id = args.graph_id
    old_name = args.old_name
    new_name = args.new_name
    graph = _get_graph(graph_id)

    # Search all node types for the old name
    node_type_endpoints = {
        "python_node_list": "/pythonnodes/",
        "crew_node_list": "/crew-nodes/",
        "code_agent_node_list": "/code-agent-nodes/",
        "llm_node_list": "/llmnodes/",
        "file_extractor_node_list": "/file-extractor-nodes/",
        "audio_transcription_node_list": "/audio-transcription-nodes/",
        "webhook_trigger_node_list": "/webhook-trigger-nodes/",
        "telegram_trigger_node_list": "/telegram-trigger-nodes/",
        "decision_table_node_list": "/decision-table-node/",
        "classification_decision_table_node_list": "/classification-decision-table-node/",
    }
    for list_key, endpoint in node_type_endpoints.items():
        for db_node in graph.get(list_key, []):
            if db_node.get("node_name") == old_name:
                node_id = db_node["id"]
                api_patch(f"{endpoint}{node_id}/", {"node_name": new_name})
                print(f"  DB node {node_id} ({list_key.replace('_list','')}): '{old_name}' → '{new_name}'")
                print(f"\nRenamed '{old_name}' → '{new_name}'")
                return

    print(f"Node '{old_name}' not found in flow {graph_id}", file=sys.stderr)
    sys.exit(1)


def cmd_sync_metadata(args):
    """Deprecated: Graph.metadata is no longer used post-RC.

    The frontend now reads positions from each node's own metadata field
    and derives connections from DB edges at load time. Graph.metadata
    is saved as empty {nodes: [], connections: []} on every UI save.
    """
    print("sync-metadata is no longer needed.")
    print("Graph.metadata is not used by the frontend or backend runtime.")
    print("All data lives in DB models. Use 'patch-*' commands to update DB directly.")


# ═══════════════════════════════════════════════════════════════════════════
# OpenCode abort
# ═══════════════════════════════════════════════════════════════════════════

def cmd_oc_abort(args):
    """Abort any in-flight request on an OpenCode session."""
    sid = getattr(args, "oc_session_id", None)
    if not sid:
        sessions = _oc_curl("/session")
        statuses = _oc_curl("/session/status") or {}
        if not sessions:
            print("No OpenCode sessions.")
            return
        for s in sessions:
            if s.get("title", "").startswith("epicstaff_"):
                st = statuses.get(s["id"], {}).get("type", "idle")
                if st != "idle":
                    sid = s["id"]
                    break
        if not sid:
            print("All epicstaff sessions are idle. Nothing to abort.")
            return
    result = _oc_curl(f"/session/{sid}/abort", method="POST")
    print(f"Abort sent to {sid}: {result}")


# ═══════════════════════════════════════════════════════════════════════════
# Run Session
# ═══════════════════════════════════════════════════════════════════════════

def cmd_run_session(args):
    """Trigger a flow session and poll until it completes or times out."""
    gid = args.graph_id
    timeout = getattr(args, "timeout", 300) or 300
    variables = {}

    var_json = getattr(args, "variables", None)
    if var_json:
        try:
            variables = json.loads(var_json)
        except json.JSONDecodeError:
            print(f"Error: --variables must be valid JSON", file=sys.stderr)
            sys.exit(1)

    print(f"Starting session for flow {gid}...")
    result = api_post("/run-session/", {"graph_id": gid, "variables": variables})
    session_id = result.get("session_id")
    if not session_id:
        print(f"Error: no session_id returned: {result}", file=sys.stderr)
        sys.exit(1)
    print(f"Session {session_id} started. Polling (timeout={timeout}s)...\n")

    poll_interval = 3
    waited = 0
    last_status = None

    while waited < timeout:
        time.sleep(poll_interval)
        waited += poll_interval

        try:
            resp = api_get(f"/sessions/{session_id}/get-updates/")
            status = resp.get("status") if isinstance(resp, dict) else resp
        except Exception as e:
            print(f"  [{waited:>4}s] Poll error: {e}")
            continue

        if status != last_status:
            print(f"  [{waited:>4}s] Status: {status}")
            last_status = status

        if isinstance(status, str) and status.lower() in ("done", "completed", "error", "stopped"):
            break

    print(f"\nSession {session_id} final status: {last_status}")

    # Fetch session details
    try:
        session = api_get(f"/sessions/{session_id}/")
        print(f"  Duration: {session.get('duration', '?')}s")
        if session.get("status_data"):
            print(f"  Status data: {json.dumps(session['status_data'], indent=2)[:500]}")
    except Exception:
        pass

    return session_id
