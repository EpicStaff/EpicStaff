"""Flow inspection, CDT read, session debugging, and OpenCode read commands."""

import json
import sys
from pathlib import Path
from datetime import datetime

from common import (
    api_get, api_get_page, _get_graph, _get_cdt_nodes,
    _discover_files, _read_from_file, _read_from_db, _read_from_metadata,
    _canonical_json, _oc_curl,
    build_id_to_name_map,
    FLOWS_DIR, _flows_dir,
)


# ═══════════════════════════════════════════════════════════════════════════
# Flow Inspection
# ═══════════════════════════════════════════════════════════════════════════

def cmd_list(args):
    """List all flows."""
    data = api_get("/graphs/")
    results = data if isinstance(data, list) else data
    for g in results:
        print(f"  [{g['id']}] {g['name']}")


def cmd_get(args):
    data = _get_graph(args.graph_id)
    if args.json:
        print(json.dumps(data, indent=2))
        return
    print(f"Flow: [{data['id']}] {data['name']}")
    print(f"Description: {data.get('description', '—')}")
    node_types = [
        ("start_node_list", "Start"), ("end_node_list", "End"),
        ("python_node_list", "Python"), ("llm_node_list", "LLM"),
        ("crew_node_list", "Crew"), ("decision_table_node_list", "Decision Table"),
        ("classification_decision_table_node_list", "CDT"),
        ("webhook_trigger_node_list", "Webhook Trigger"),
        ("telegram_trigger_node_list", "Telegram Trigger"),
        ("code_agent_node_list", "Code Agent"),
    ]
    print("\nNodes:")
    for key, label in node_types:
        for n in data.get(key, []):
            print(f"  [{label}] {n.get('node_name', '?')} (id={n.get('id')})")


def cmd_nodes(args):
    """List all nodes with DB IDs."""
    graph = _get_graph(args.graph_id)
    node_lists = [
        ("start_node_list", "start"), ("end_node_list", "end"),
        ("python_node_list", "python"), ("crew_node_list", "crew"),
        ("classification_decision_table_node_list", "cdt"),
        ("decision_table_node_list", "dt"),
        ("webhook_trigger_node_list", "webhook"), ("telegram_trigger_node_list", "telegram"),
        ("llm_node_list", "llm"),
        ("code_agent_node_list", "code-agent"),
    ]
    print(f"Nodes in flow {args.graph_id}:\n")
    for key, ntype in node_lists:
        for n in graph.get(key, []):
            name = n.get("node_name", "?")
            nid = n.get("id", "?")
            extra = ""
            if ntype == "python":
                code_len = len((n.get("python_code", {}) or {}).get("code", "") or "")
                libs = (n.get("python_code", {}) or {}).get("libraries", "")
                extra = f" code={code_len}c"
                if libs:
                    extra += f" libs={libs}"
            elif ntype == "cdt":
                groups = len(n.get("condition_groups", []))
                extra = f" groups={groups}"
            elif ntype == "crew":
                extra = f" crew_id={n.get('crew_id')}"
            elif ntype == "code-agent":
                mode = n.get("agent_mode", "build")
                llm = n.get("llm_config")
                extra = f" mode={mode} llm_config={llm}"
            print(f"  {ntype:10s} id={nid:5} {name}{extra}")


def cmd_edges(args):
    """Show DB edges (backend non-CDT routing).

    NOTE: EdgeViewSet has no filter_backends, so ?graph=<id> is silently ignored.
    We filter client-side by comparing edge graph FK against args.graph_id.
    """
    graph = _get_graph(args.graph_id)
    id_to_name = build_id_to_name_map(graph)
    all_edges = api_get(f"/edges/")
    if isinstance(all_edges, dict):
        all_edges = all_edges.get("results", [])
    edges = [e for e in all_edges if e.get("graph") == args.graph_id]
    print(f"DB edges for flow {args.graph_id} ({len(edges)}):\n")
    for e in edges:
        src = id_to_name.get(e['start_node_id'], f"?#{e['start_node_id']}")
        tgt = id_to_name.get(e['end_node_id'], f"?#{e['end_node_id']}")
        print(f"  {src} → {tgt}  (id={e['id']}, {e['start_node_id']}→{e['end_node_id']})")


def cmd_connections(args):
    """Show all graph connections: edges + conditional edges + DT routing (from DB)."""
    graph = _get_graph(args.graph_id)
    id_to_name = build_id_to_name_map(graph)

    # Regular edges
    edges = graph.get("edge_list", [])
    print(f"Edges for flow {args.graph_id} ({len(edges)}):\n")
    for e in edges:
        src = id_to_name.get(e.get("start_node_id"), f"?#{e.get('start_node_id')}")
        tgt = id_to_name.get(e.get("end_node_id"), f"?#{e.get('end_node_id')}")
        print(f"  {src} → {tgt}  (edge id={e['id']})")

    # Conditional edges
    ce_list = graph.get("conditional_edge_list", [])
    if ce_list:
        print(f"\nConditional edges ({len(ce_list)}):\n")
        for ce in ce_list:
            src = id_to_name.get(ce.get("source_node_id"), f"?#{ce.get('source_node_id')}")
            then = id_to_name.get(ce.get("then_node_id"), f"?#{ce.get('then_node_id')}")
            print(f"  {src} → {then}  (ce id={ce['id']}, condition={ce.get('condition', '?')})")

    # DT condition group routing
    dt_types = [
        ("classification_decision_table_node_list", "CDT"),
        ("decision_table_node_list", "DT"),
    ]
    for list_key, label in dt_types:
        for dt in graph.get(list_key, []):
            groups = dt.get("condition_groups", [])
            if not groups:
                continue
            print(f"\n{label} '{dt['node_name']}' routing:")
            for g in groups:
                next_node = g.get("next_node", "")
                print(f"  [{g.get('order','-')}] {g.get('group_name','?')} → {next_node or '(empty)'}")
            default = dt.get("default_next_node")
            error = dt.get("next_error_node")
            if default:
                print(f"  default → {default}")
            if error:
                print(f"  error → {error}")


def cmd_route_map(args):
    """Verify CDT/DT route maps from DB condition groups."""
    graph = _get_graph(args.graph_id)
    id_to_name = build_id_to_name_map(graph)

    dt_types = [
        ("classification_decision_table_node_list", "CDT"),
        ("decision_table_node_list", "DT"),
    ]
    print(f"Route maps for flow {args.graph_id}:\n")
    all_ok = True
    found_any = False

    for list_key, label in dt_types:
        for dt in graph.get(list_key, []):
            found_any = True
            db_name = dt["node_name"]
            groups = dt.get("condition_groups", [])
            route_map = {}
            for g in groups:
                gname = g.get("group_name", "?")
                next_node = g.get("next_node")
                if next_node:
                    route_map[gname] = next_node

            if route_map:
                print(f"  ✅ {label} '{db_name}':")
                for gname, target in route_map.items():
                    print(f"      {gname} → {target}")
            else:
                has_groups = len(groups) > 0
                if has_groups:
                    print(f"  ⚠️  {label} '{db_name}': has {len(groups)} groups but no next_node routing")
                    all_ok = False
                else:
                    print(f"  ℹ️  {label} '{db_name}': no condition groups")

            default = dt.get("default_next_node")
            error = dt.get("next_error_node")
            if default:
                print(f"      default → {default}")
            if error:
                print(f"      error → {error}")

    if not found_any:
        print("  No CDT or DT nodes in this flow.")
    elif all_ok:
        print("\n  All route maps OK.")
    else:
        print("\n  ⚠️  Issues found — check condition group next_node values.")


# ═══════════════════════════════════════════════════════════════════════════
# CDT Operations
# ═══════════════════════════════════════════════════════════════════════════

def cmd_cdt(args):
    """Show CDT node details."""
    graph = _get_graph(args.graph_id)
    cdts = graph.get("classification_decision_table_node_list", [])
    if not cdts:
        print("No CDT nodes found.")
        return
    for cdt in cdts:
        print(f"\nCDT: {cdt.get('node_name')} (id={cdt.get('id')})")
        print(f"  Default Next: {cdt.get('default_next_node') or '(empty)'}")
        print(f"  Error Next: {cdt.get('next_error_node') or '(empty)'}")
        print(f"  Input Map: {json.dumps(cdt.get('input_map', {}), indent=4)}")
        cgs = cdt.get("condition_groups", [])
        if args.json:
            print(json.dumps(cgs, indent=2))
            continue
        for i, cg in enumerate(cgs):
            print(f"\n  --- Row {i+1}: {cg.get('group_name', '?')} ---")
            print(f"    Expression: {cg.get('expression') or '—'}")
            fe = cg.get("field_expressions", {})
            if fe:
                for fname, fexpr in fe.items():
                    print(f"    Field [{fname}]: {fexpr or '—'}")
            print(f"    Manipulation: {cg.get('manipulation') or '—'}")
            print(f"    Route Code: {cg.get('route_code', '—')}")
            print(f"    Continue: {cg.get('continue', cg.get('continue_flag', False))}")
            print(f"    Dock Visible: {cg.get('dock_visible', True)}")
            print(f"    Prompt: {cg.get('prompt_id') or '—'}")


def cmd_cdt_code(args):
    """Show CDT pre/post computation code."""
    if args.cdt_id:
        nodes = [api_get(f"/classification-decision-table-node/{args.cdt_id}/")]
    else:
        nodes = _get_cdt_nodes(args.graph_id)

    for cdt in nodes:
        name = cdt.get("node_name", "?")
        cdt_id = cdt.get("id", "?")
        print(f"\n{'='*60}")
        print(f"CDT: {name} (id={cdt_id})")
        print(f"pre_input_map: {json.dumps(cdt.get('pre_input_map'), indent=2)}")
        print(f"pre_output_variable_path: {cdt.get('pre_output_variable_path')}")
        pre = cdt.get("pre_computation_code", "")
        if pre:
            print(f"\n--- PRE-COMPUTATION CODE ({len(pre.splitlines())} lines) ---")
            for i, line in enumerate(pre.splitlines(), 1):
                print(f"  {i:4d}: {line}")
        else:
            print("\n  (no pre-computation code)")
        print(f"\npost_input_map: {json.dumps(cdt.get('post_input_map'), indent=2)}")
        print(f"post_output_variable_path: {cdt.get('post_output_variable_path')}")
        post = cdt.get("post_computation_code", "")
        if post:
            print(f"\n--- POST-COMPUTATION CODE ({len(post.splitlines())} lines) ---")
            for i, line in enumerate(post.splitlines(), 1):
                print(f"  {i:4d}: {line}")
        else:
            print("\n  (no post-computation code)")


def cmd_cdt_prompts(args):
    """Show CDT prompts."""
    cdts = _get_cdt_nodes(args.graph_id)
    for cdt in cdts:
        prompts = cdt.get("prompts", {})
        if not prompts:
            continue
        print(f"\n{cdt['node_name']} (id={cdt['id']}): {len(prompts)} prompts")
        for pid, pdata in prompts.items():
            rv = pdata.get("result_variable", "")
            llm = pdata.get("llm_id", "")
            pt = (pdata.get("prompt_text", "") or "")[:80]
            print(f"  {pid}: result_variable=\"{rv}\" llm_id={llm}")
            print(f"    prompt: {pt}...")


# ═══════════════════════════════════════════════════════════════════════════
# Session Debugging
# ═══════════════════════════════════════════════════════════════════════════

INTERESTING_OUTPUT_KEYS = [
    "user_message_text", "route_code", "route_label", "is_leader",
    "raw", "message_id_already_seen", "chat_id", "result",
    "start_route_code", "end_route_code", "stage",
]
COMPACT_SKIP_TYPES = {"condition_group", "condition_group_manipulation"}


def _format_output(out, max_len=120):
    if not out:
        return ""
    if isinstance(out, str):
        return out[:max_len]
    if isinstance(out, dict):
        parts = []
        for k in INTERESTING_OUTPUT_KEYS:
            if k in out:
                v = str(out[k])
                if len(v) > max_len:
                    v = v[:max_len - 3] + "..."
                parts.append(f"{k}={v}")
        if parts:
            return " | ".join(parts)
        keys = list(out.keys())[:8]
        return f"[{', '.join(keys)}]"
    return str(out)[:max_len]


def _extract_trigger_text(inp):
    if not isinstance(inp, dict):
        return ""
    tp = inp.get("trigger_payload", {})
    if isinstance(tp, dict):
        msg = tp.get("message", {})
        if isinstance(msg, dict):
            text = msg.get("text", "") or msg.get("argumentText", "")
            if text:
                return text
    return ""


def _print_session(session_id, messages, compact=False, json_mode=False):
    if json_mode:
        print(json.dumps(messages, indent=2, default=str))
        return

    trigger_text = ""
    for m in messages:
        md = m.get("message_data", {})
        text = _extract_trigger_text(md.get("input", {}))
        if text:
            trigger_text = text
            break

    print(f"\n{'='*80}")
    print(f"SESSION {session_id}  ({len(messages)} messages)")
    if trigger_text:
        print(f"User message: \"{trigger_text}\"")
    print(f"{'='*80}")

    for m in messages:
        md = m.get("message_data", {})
        mtype = md.get("message_type", "?")
        name = m.get("name", "?")
        out = md.get("output", {})

        if compact and mtype in COMPACT_SKIP_TYPES:
            continue

        out_str = _format_output(out)
        ts = m.get("created_at", "")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                ts = dt.strftime("%H:%M:%S.%f")[:-3]
            except Exception:
                ts = ts[:19]

        error = md.get("error", "")
        if error:
            out_str = f"ERROR: {str(error)[:200]}"

        group = md.get("group_name", "")
        result = md.get("result")
        matched = md.get("matched_condition", "")
        if group and result is not None:
            out_str = f"group={group} result={result}"
        elif group:
            out_str = f"group={group}"
        if matched:
            out_str += f" matched={matched}"

        line = f"  {ts} [{mtype:30s}] {name:35s}"
        if out_str:
            line += f" | {out_str}"
        print(line)


def cmd_sessions(args):
    """Last N sessions for a flow (or all flows if -g not given)."""
    params = {"ordering": "-id", "limit": args.n}
    if args.graph_id:
        params["graph"] = args.graph_id
    sessions = api_get_page("/sessions/", params)
    if not sessions:
        scope = f"flow {args.graph_id}" if args.graph_id else "any flow"
        print(f"No sessions found for {scope}")
        return
    scope = f"flow {args.graph_id}" if args.graph_id else "all flows"
    print(f"Last {len(sessions)} sessions ({scope}):")
    for s in sessions:
        graph_label = f" flow={s.get('graph','?')}" if not args.graph_id else ""
        print(f"  Session {s['id']}:{graph_label} status={s['status']}, created={s.get('created_at','?')[:19]}")
    for s in reversed(sessions):
        msgs = api_get("/graph-session-messages/", {"session_id": s["id"], "ordering": "id", "limit": 100})
        _print_session(s["id"], msgs, compact=args.compact, json_mode=args.json)


def cmd_session(args):
    """Show specific session(s)."""
    for sid in args.session_ids:
        msgs = api_get("/graph-session-messages/", {"session_id": sid, "ordering": "id"})
        if not msgs:
            print(f"\nSession {sid}: no messages found")
            continue
        _print_session(sid, msgs, compact=args.compact, json_mode=args.json)


def cmd_session_inspect(args):
    """Inspect what each node received as input and produced as output."""
    full = getattr(args, 'full', False)
    for sid in args.session_ids:
        msgs = api_get("/graph-session-messages/", {"session_id": sid, "ordering": "id"})
        if not msgs:
            print(f"\nSession {sid}: no messages found")
            continue
        print(f"\n{'='*80}")
        print(f"SESSION {sid} — Node Input/Output Inspection")
        print(f"{'='*80}")
        seen_nodes = {}
        for m in msgs:
            md = m.get("message_data", {})
            mtype = md.get("message_type", "")
            name = m.get("name", "?")
            inp = md.get("input", {})
            out = md.get("output", {})
            error = md.get("error", "") or md.get("details", "")
            if mtype == "start" and isinstance(inp, dict) and inp:
                seen_nodes[name] = {"input": inp}
                print(f"\n  {name} (input):")
                for k, v in inp.items():
                    vstr = str(v)
                    if not full and len(vstr) > 120:
                        vstr = vstr[:120] + "..."
                    print(f"    {k}: {vstr}")
            elif mtype == "finish" and isinstance(out, dict) and out:
                print(f"\n  {name} (output):")
                for k, v in out.items():
                    if full:
                        vstr = json.dumps(v, indent=2, default=str) if isinstance(v, (dict, list)) else str(v)
                    else:
                        vstr = str(v)
                        if len(vstr) > 120:
                            vstr = vstr[:120] + "..."
                    print(f"    {k}: {vstr}")
            elif error and name:
                estr = str(error)
                if not full and len(estr) > 200:
                    estr = estr[:200] + "..."
                print(f"\n  {name} (error): {estr}")


def cmd_session_timings(args):
    """Show per-node timing breakdown for session(s)."""
    for sid in args.session_ids:
        msgs = api_get("/graph-session-messages/", {"session_id": sid, "ordering": "id"})
        if not msgs:
            print(f"\nSession {sid}: no messages found")
            continue

        # Parse timestamps
        events = []
        for m in msgs:
            md = m.get("message_data", {})
            mtype = md.get("message_type", "")
            name = m.get("name", "") or ""
            ts_str = m.get("created_at", "")
            if not ts_str:
                continue
            try:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except Exception:
                continue
            events.append({"ts": dt, "type": mtype, "name": name})

        if not events:
            print(f"\nSession {sid}: no timestamped messages")
            continue

        events.sort(key=lambda e: e["ts"])
        t0 = events[0]["ts"]
        total_s = (events[-1]["ts"] - t0).total_seconds()

        print(f"\n{'='*80}")
        print(f"SESSION {sid} — Timings ({total_s:.1f}s total)")
        print(f"{'='*80}")

        prev_ts = None
        node_durations = {}
        node_start = {}

        for e in events:
            ts = e["ts"]
            mtype = e["type"]
            name = e["name"]
            offset_s = (ts - t0).total_seconds()
            delta_ms = (ts - prev_ts).total_seconds() * 1000 if prev_ts else 0
            prev_ts = ts

            ts_fmt = ts.strftime("%H:%M:%S.%f")[:-3]
            delta_str = f"+{delta_ms:7.0f}ms" if delta_ms else "         "
            print(f"  {ts_fmt} {delta_str} [{mtype:30s}] {name}")

            # Track node durations (start → finish)
            if mtype == "start" and name:
                node_start[name] = ts
            elif mtype == "finish" and name and name in node_start:
                dur = (ts - node_start[name]).total_seconds()
                node_durations[name] = node_durations.get(name, 0) + dur

        if node_durations:
            print(f"\n  Node durations:")
            for name, dur in sorted(node_durations.items(), key=lambda x: -x[1]):
                pct = (dur / total_s * 100) if total_s > 0 else 0
                bar = "█" * int(pct / 2)
                print(f"    {dur:6.1f}s ({pct:4.1f}%) {name:40s} {bar}")


def cmd_vars(args):
    """Show persistent variables."""
    results = api_get("/graph-organizations/")
    go = None
    for r in results:
        if r.get("graph") == args.graph_id:
            go = r
            break
    if not go:
        print(f"No GraphOrganization for flow {args.graph_id}")
        return
    pv = go.get("persistent_variables", {})
    if args.json:
        print(json.dumps(pv, indent=2, default=str))
        return
    print(f"GraphOrganization id={go['id']}, graph={go['graph']}")
    print(f"Persistent variable keys: {list(pv.keys())}")
    for k, v in pv.items():
        if k == "message_history" and isinstance(v, dict):
            print(f"\n  message_history ({len(v)} chats):")
            for cid, hist in v.items():
                if isinstance(hist, list):
                    print(f"    {cid}: {len(hist)} entries")
        elif isinstance(v, dict):
            print(f"  {k}: dict with {len(v)} keys: {list(v.keys())[:8]}")
        elif isinstance(v, list):
            print(f"  {k}: list with {len(v)} items")
        else:
            print(f"  {k}: {str(v)[:100]}")


def cmd_history(args):
    """Show message_history."""
    results = api_get("/graph-organizations/")
    go = None
    for r in results:
        if r.get("graph") == args.graph_id:
            go = r
            break
    if not go:
        print(f"No GraphOrganization for flow {args.graph_id}")
        return
    mh = go.get("persistent_variables", {}).get("message_history", {})
    if not mh:
        print("No message_history in persistent variables")
        return
    if args.chat_id:
        if args.chat_id not in mh:
            print(f"Chat ID '{args.chat_id}' not found. Available: {list(mh.keys())}")
            return
        chats = {args.chat_id: mh[args.chat_id]}
    else:
        chats = mh
    for cid, history in chats.items():
        if not isinstance(history, list):
            print(f"  {cid}: (not a list)")
            continue
        print(f"  {cid}: {len(history)} entries")
        for i, entry in enumerate(history[-50:]):
            role = entry.get("role", "?")
            content = str(entry.get("content", ""))[:120]
            idx = max(0, len(history) - 50) + i
            print(f"    [{idx:2d}] {role:10s} | {content}")


def cmd_trace(args):
    """Trace message_history through a session."""
    msgs = api_get("/graph-session-messages/", {"session_id": args.session_id, "ordering": "id"})
    if not msgs:
        print(f"No messages for session {args.session_id}")
        return
    print(f"\nSession {args.session_id}: tracing message_history")
    print("=" * 60)
    for m in msgs:
        md = m.get("message_data", {})
        mtype = md.get("message_type", "")
        name = m.get("name", "?")
        state = md.get("state", {})
        mh = (state.get("variables", {}) or {}).get("message_history")
        if mh and isinstance(mh, dict):
            total = sum(len(v) for v in mh.values() if isinstance(v, list))
            chats = {k: len(v) for k, v in mh.items() if isinstance(v, list)}
            print(f"  [{mtype:15s}] {name:35s} | {total} entries: {chats}")


def cmd_crew_input(args):
    """Show Crew node input/output."""
    msgs = api_get("/graph-session-messages/", {"session_id": args.session_id, "ordering": "id"})
    if not msgs:
        print(f"No messages for session {args.session_id}")
        return
    print(f"\nSession {args.session_id}: Crew node inputs")
    print("=" * 60)
    for m in msgs:
        md = m.get("message_data", {})
        mtype = md.get("message_type", "")
        name = m.get("name", "?")
        if mtype == "start" and ("reply" in name.lower() or "crew" in name.lower() or "#" in name):
            inp = md.get("input", {})
            if not isinstance(inp, dict):
                continue
            print(f"\n  Crew node: {name}")
            for k, v in inp.items():
                if k == "conversation_context" and isinstance(v, list):
                    print(f"    conversation_context: {len(v)} messages")
                    for i, entry in enumerate(v):
                        role = entry.get("role", "?")
                        content = str(entry.get("content", ""))[:120]
                        print(f"      [{i:2d}] {role:10s} | {content}")
                else:
                    val = str(v)
                    if len(val) > 150:
                        val = val[:147] + "..."
                    print(f"    {k}: {val}")
        if mtype == "agent_finish":
            out = md.get("output", {})
            text = ""
            if isinstance(out, dict):
                text = str(out.get("raw", out.get("text", out)))[:200]
            elif isinstance(out, str):
                text = out[:200]
            print(f"\n  Agent reply: {text}")


# ═══════════════════════════════════════════════════════════════════════════
# Verify / Export compare
# ═══════════════════════════════════════════════════════════════════════════

def cmd_verify(args):
    """Three-way verify: file <-> DB <-> metadata."""
    if not args.path:
        args.path = str(_flows_dir(args.graph_id))
    specs = _discover_files(args.path)
    if not specs:
        print(f"No recognized files in: {args.path}")
        sys.exit(1)
    verbose = getattr(args, "verbose", False)
    print(f"Verifying {len(specs)} file(s) against flow {args.graph_id}:\n")
    total_ok, total_issues = 0, 0
    for spec in specs:
        try:
            file_data = _read_from_file(spec)
            db_data, node_name = _read_from_db(spec, args.graph_id)
            fname = Path(spec.path).name
            if db_data is None:
                print(f"  ⚠️  {fname}: node not found in DB for slug '{spec.slug}'")
                total_issues += 1
                continue
            meta_data = _read_from_metadata(spec, args.graph_id, node_name)
            if isinstance(file_data, str):
                file_db = file_data == db_data
                file_meta = file_data == (meta_data or "")
                db_meta = db_data == (meta_data or "")
            else:
                fj, dj = _canonical_json(file_data), _canonical_json(db_data)
                mj = _canonical_json(meta_data) if meta_data is not None else None
                file_db = fj == dj
                file_meta = fj == mj if mj else False
                db_meta = dj == mj if mj else False
            s = lambda ok: "✅" if ok else "❌"
            target = f"CDT '{node_name}'" if spec.kind == "cdt" else f"Python '{node_name}'"
            print(f"  {fname} → {target}")
            print(f"      File↔DB={s(file_db)}  File↔Meta={s(file_meta)}  DB↔Meta={s(db_meta)}")
            if file_db and file_meta and db_meta:
                total_ok += 1
            else:
                total_issues += 1
                if verbose and isinstance(file_data, str) and not file_db:
                    print(f"      File↔DB: file_len={len(file_data)} db_len={len(db_data or '')}")
        except Exception as e:
            print(f"  ❌ {Path(spec.path).name}: {e}")
            total_issues += 1
    print(f"\n{'─'*50}")
    print(f"  Checked: {total_ok + total_issues}  Synced: {total_ok}  Issues: {total_issues}")
    if total_issues:
        print("  Run 'push' to sync, or 'pull' to update local files.")
        sys.exit(1)
    else:
        print("  ✅ All three representations are in sync.")


def cmd_export_compare(args):
    """Compare export JSON with current DB state."""
    with open(args.file) as f:
        export = json.load(f)
    graph_id = args.graph_id or export.get("id")
    if not graph_id:
        print("Cannot determine graph ID. Use -g or ensure export has 'id'.")
        sys.exit(1)
    graph = _get_graph(graph_id)
    print(f"=== EXPORT vs CURRENT DB (flow {graph_id}) ===\n")

    export_py = {n["node_name"]: n for n in export.get("python_node_list", [])}
    current_py = {n["node_name"]: n for n in graph.get("python_node_list", [])}
    print(f"Python nodes: export={len(export_py)} current={len(current_py)}")
    for name in sorted(set(list(export_py.keys()) + list(current_py.keys()))):
        e, c = export_py.get(name), current_py.get(name)
        if e and not c:
            print(f"  ❌ {name}: IN EXPORT ONLY")
        elif c and not e:
            print(f"  ➕ {name}: IN CURRENT ONLY")
        else:
            e_code = (e.get("python_code", {}) or {}).get("code", "") or ""
            c_code = (c.get("python_code", {}) or {}).get("code", "") or ""
            match = e_code.strip() == c_code.strip()
            status = "✅" if match else "⚠️"
            detail = "" if match else f" code: {len(e_code)}c vs {len(c_code)}c"
            print(f"  {status} {name}{detail}")

    export_cdt = {n["node_name"]: n for n in export.get("classification_decision_table_node_list", [])}
    current_cdts = _get_cdt_nodes(graph_id)
    current_cdt = {n["node_name"]: n for n in current_cdts}
    print(f"\nCDT nodes: export={len(export_cdt)} current={len(current_cdt)}")
    for name in sorted(set(list(export_cdt.keys()) + list(current_cdt.keys()))):
        e, c = export_cdt.get(name), current_cdt.get(name)
        if e and not c:
            print(f"  ❌ {name}: IN EXPORT ONLY")
        elif c and not e:
            print(f"  ➕ {name}: IN CURRENT ONLY")
        else:
            issues = []
            eg, cg = len(e.get("condition_groups", [])), len(c.get("condition_groups", []))
            if eg != cg:
                issues.append(f"groups: {eg} vs {cg}")
            ep = len(e.get("prompts", {})), len(c.get("prompts", {}))
            if ep[0] != ep[1]:
                issues.append(f"prompts: {ep[0]} vs {ep[1]}")
            for field in ("pre_computation_code", "post_computation_code"):
                el, cl = len((e.get(field) or "").strip()), len((c.get(field) or "").strip())
                if el != cl:
                    short = field.replace("_computation_code", "")
                    issues.append(f"{short}: {el} vs {cl}")
            for field in ("pre_input_map", "post_input_map"):
                ej = json.dumps(e.get(field) or {}, sort_keys=True)
                cj = json.dumps(c.get(field) or {}, sort_keys=True)
                if ej != cj:
                    issues.append(f"{field} differs")
            status = "✅" if not issues else "⚠️"
            print(f"  {status} {name}: {' | '.join(issues) if issues else 'identical'}")

    export_edges = export.get("edge_list", [])
    current_edges = api_get(f"/edges/", {"graph": graph_id})
    if isinstance(current_edges, dict):
        current_edges = current_edges.get("results", [])
    print(f"\nEdges: export={len(export_edges)} current={len(current_edges)}")


# ═══════════════════════════════════════════════════════════════════════════
# OpenCode read operations
# ═══════════════════════════════════════════════════════════════════════════

def cmd_oc_status(args):
    """Show OpenCode session statuses (idle/busy)."""
    statuses = _oc_curl("/session/status")
    if statuses is None:
        print("Cannot reach OpenCode in sandbox container.")
        return
    if not statuses:
        print("All OpenCode sessions idle (no active requests).")
        return
    print("OpenCode session statuses:")
    for sid, s in statuses.items():
        stype = s.get("type", "?")
        print(f"  {sid}: {stype}")


def cmd_oc_sessions(args):
    """List OpenCode sessions with details."""
    sessions = _oc_curl("/session")
    if sessions is None:
        print("Cannot reach OpenCode in sandbox container.")
        return
    if not sessions:
        print("No OpenCode sessions.")
        return
    statuses = _oc_curl("/session/status") or {}
    print(f"OpenCode sessions ({len(sessions)}):")
    for s in sessions:
        sid = s.get("id", "?")
        title = s.get("title", "?")
        time_info = s.get("time", {})
        updated = time_info.get("updated", 0)
        status = statuses.get(sid, {}).get("type", "idle")
        if updated:
            from datetime import datetime
            ts = datetime.fromtimestamp(updated / 1000).strftime("%Y-%m-%d %H:%M:%S")
        else:
            ts = "?"
        msgs = _oc_curl(f"/session/{sid}/message")
        msg_count = len(msgs) if isinstance(msgs, list) else "?"
        stale_mark = ""
        if status != "idle" and updated:
            import time as _time
            age_min = (_time.time() * 1000 - updated) / 60000
            if age_min > 5:
                stale_mark = f" ⚠️  STALE ({age_min:.0f}min since last update)"
        print(f"  [{status:8s}] {sid}")
        print(f"           title={title}  msgs={msg_count}  updated={ts}{stale_mark}")


def cmd_oc_messages(args):
    """Show last N messages in an OpenCode session."""
    sid = getattr(args, "oc_session_id", None)
    if not sid:
        sessions = _oc_curl("/session")
        if not sessions:
            print("No OpenCode sessions.")
            return
        for s in sessions:
            if s.get("title", "").startswith("epicstaff_"):
                sid = s["id"]
                break
        if not sid:
            sid = sessions[0]["id"] if sessions else None
    if not sid:
        print("No session found.")
        return
    msgs = _oc_curl(f"/session/{sid}/message")
    if not isinstance(msgs, list):
        print(f"Cannot read messages for {sid}")
        return
    n = getattr(args, "n", 10) or 10
    total = len(msgs)
    show = msgs[-n:]
    print(f"OpenCode session {sid}: {total} messages (showing last {len(show)})")
    for i, m in enumerate(show):
        idx = total - len(show) + i
        role = m.get("role", "?")
        parts = m.get("parts", [])
        text = ""
        tool = ""
        for p in parts:
            if p.get("type") == "text":
                text = p.get("text", "")
            elif p.get("type") == "tool-invocation":
                ti = p.get("toolInvocation", {})
                tool = f"[tool: {ti.get('toolName', '?')}]"
        preview = (tool or text)[:120]
        if len(text) > 120 and not tool:
            preview += "..."
        print(f"  [{idx:3d}] {role:12s} | {preview}")


def cmd_oc_session(args):
    """Show full OpenCode session conversation in friendly format.

    Accepts an EpicStaff session ID (numeric) or an OpenCode session ID (ses_...).
    Tries the OpenCode API first; falls back to Django graph-session-messages.
    """
    raw_id = args.oc_session_id
    oc_sid = None
    es_sid = None

    # Determine if it's an EpicStaff session ID or an OC session ID
    if raw_id and raw_id.isdigit():
        es_sid = int(raw_id)
    elif raw_id and raw_id.startswith("ses_"):
        oc_sid = raw_id
    elif raw_id:
        # Could be a partial match — try as EpicStaff session ID
        try:
            es_sid = int(raw_id)
        except ValueError:
            oc_sid = raw_id

    # If we have an EpicStaff session ID, look up the OC session ID from finish message
    if es_sid and not oc_sid:
        msgs = api_get("/graph-session-messages/", params={"session_id": es_sid})
        for m in msgs:
            md = m.get("message_data", {})
            if md.get("message_type") == "finish":
                out = md.get("output", {})
                if isinstance(out, dict) and out.get("session_id"):
                    oc_sid = out["session_id"]
                    break

    # Try OpenCode API first
    oc_msgs = None
    if oc_sid:
        oc_msgs = _oc_curl(f"/session/{oc_sid}/message")
        if isinstance(oc_msgs, list) and oc_msgs:
            _print_oc_session_from_oc(oc_sid, oc_msgs, es_sid)
            return

    # Fall back to Django graph-session-messages
    if es_sid:
        _print_oc_session_from_django(es_sid, oc_sid)
        return

    # No data found
    if oc_sid:
        print(f"No messages found for OC session {oc_sid} (container may have been rebuilt).")
        if not es_sid:
            print("Tip: pass an EpicStaff session ID (numeric) to use Django fallback.")
    else:
        print("No session found. Pass an EpicStaff session ID or OpenCode session ID.")


def _print_oc_session_from_oc(oc_sid, msgs, es_sid=None):
    """Format OpenCode API messages into friendly output."""
    header = f"OpenCode session: {oc_sid}"
    if es_sid:
        header += f"  (EpicStaff session {es_sid})"
    print(f"\n{'=' * 80}")
    print(header)
    print(f"{'=' * 80}\n")

    for i, m in enumerate(msgs):
        role = m.get("role", "?")
        parts = m.get("parts", [])

        if role == "user":
            print(f"{'─' * 60}")
            print(f"👤 USER (message {i})")
            print(f"{'─' * 60}")
            for p in parts:
                if p.get("type") == "text":
                    text = p.get("text", "")
                    if len(text) > 500:
                        print(f"{text[:500]}...")
                        print(f"  [...{len(text)} chars total]")
                    else:
                        print(text)
            print()

        elif role == "assistant":
            print(f"{'─' * 60}")
            print(f"🤖 ASSISTANT (message {i})")
            print(f"{'─' * 60}")
            for p in parts:
                pt = p.get("type", "")
                if pt == "reasoning":
                    text = p.get("text", "")
                    if text:
                        lines = text.strip().split("\n")
                        print(f"  💭 Reasoning ({len(text)} chars):")
                        for line in lines[:10]:
                            print(f"    {line}")
                        if len(lines) > 10:
                            print(f"    [...{len(lines)} lines total]")
                elif pt == "text":
                    text = p.get("text", "")
                    if len(text) > 1000:
                        print(f"  📝 Answer ({len(text)} chars):")
                        print(text[:1000])
                        print(f"  [...truncated, {len(text)} chars total]")
                    else:
                        print(f"  📝 Answer:")
                        print(text)
                elif pt == "tool":
                    state = p.get("state", {}) or {}
                    name = p.get("tool", "") or p.get("name", "tool")
                    status = state.get("status", "?")
                    inp = state.get("input", "")
                    out = state.get("output", "")
                    inp_str = str(inp)[:200] if inp else ""
                    out_str = str(out)[:200] if out else ""
                    icon = "✅" if status in ("completed", "done") else "🔧"
                    print(f"  {icon} Tool: {name} [{status}]")
                    if inp_str:
                        print(f"       input:  {inp_str}")
                    if out_str:
                        print(f"       output: {out_str}")
            print()

    print(f"{'=' * 80}")
    print(f"Total: {len(msgs)} messages")
    print(f"{'=' * 80}")


def _print_oc_session_from_django(es_sid, oc_sid=None):
    """Format Django graph-session-messages into friendly output."""
    msgs = api_get("/graph-session-messages/", params={"session_id": es_sid})
    if not msgs:
        print(f"No messages found for EpicStaff session {es_sid}.")
        return

    header = f"EpicStaff session {es_sid}"
    if oc_sid:
        header += f"  (OC: {oc_sid})"
    print(f"\n{'=' * 80}")
    print(f"{header}  [Django fallback — OC messages unavailable]")
    print(f"{'=' * 80}\n")

    # Collect messages by type
    prompt = None
    thinking_steps = []
    final_answer = None
    output_data = None

    for m in msgs:
        md = m.get("message_data", {})
        mt = md.get("message_type", "")
        ts = m.get("created_at", "")[:19] if m.get("created_at") else ""

        if mt == "start":
            inp = md.get("input", {})
            if isinstance(inp, dict):
                prompt = inp.get("prompt", "")
                tools_mode = inp.get("tools", "")
                action = inp.get("action", "")

        elif mt == "code_agent_stream":
            text = md.get("text", "")
            is_final = md.get("is_final", False)
            if is_final:
                final_answer = text
            else:
                thinking_steps.append({"text": text, "ts": ts})

        elif mt == "finish":
            output_data = md.get("output", {})

    # Print prompt
    if prompt:
        print(f"{'─' * 60}")
        print(f"👤 PROMPT")
        print(f"{'─' * 60}")
        if len(prompt) > 500:
            print(f"{prompt[:500]}...")
            print(f"  [...{len(prompt)} chars total]")
        else:
            print(prompt)
        print()

    # Print thinking steps
    if thinking_steps:
        print(f"{'─' * 60}")
        print(f"💭 THINKING ({len(thinking_steps)} steps)")
        print(f"{'─' * 60}")
        for i, step in enumerate(thinking_steps):
            text = step["text"]
            ts = step.get("ts", "")
            ts_label = f" [{ts}]" if ts else ""
            lines = text.strip().split("\n")
            first_line = lines[0][:120] if lines else ""
            print(f"  {i + 1}. {first_line}{ts_label}")
            if len(lines) > 1:
                for line in lines[1:5]:
                    print(f"     {line[:120]}")
                if len(lines) > 5:
                    print(f"     [...{len(lines)} lines total]")
        print()

    # Print final answer
    if final_answer:
        print(f"{'─' * 60}")
        print(f"📝 FINAL ANSWER ({len(final_answer)} chars)")
        print(f"{'─' * 60}")
        if len(final_answer) > 2000:
            print(final_answer[:2000])
            print(f"\n  [...truncated, {len(final_answer)} chars total]")
        else:
            print(final_answer)
        print()

    # Print output metadata
    if output_data and isinstance(output_data, dict):
        print(f"{'─' * 60}")
        print(f"📊 OUTPUT")
        print(f"{'─' * 60}")
        for k, v in output_data.items():
            if k == "message":
                continue  # already shown as final answer
            val_str = str(v)
            if len(val_str) > 100:
                val_str = val_str[:100] + "..."
            print(f"  {k}: {val_str}")
        print()

    print(f"{'=' * 80}")
    print(f"Total: {len(msgs)} messages from Django API")
    print(f"{'=' * 80}")


# ═══════════════════════════════════════════════════════════════════════════
# Flow Testing (structural)
# ═══════════════════════════════════════════════════════════════════════════

def cmd_test_flow(args):
    """Verify flow structure: nodes, edges, connections, CDT groups, local files."""
    gid = args.graph_id
    verbose = getattr(args, "verbose", False)
    do_verify = getattr(args, "verify", False)
    passed = 0
    failed = 0

    def _check(label, ok, detail=""):
        nonlocal passed, failed
        icon = "\u2713" if ok else "\u2717"
        status = "PASS" if ok else "FAIL"
        msg = f"  {icon} {status}  {label}"
        if detail:
            msg += f"  \u2014 {detail}"
        print(msg)
        if ok:
            passed += 1
        else:
            failed += 1
        return ok

    print(f"Testing flow {gid}...\n")

    # 1. Flow exists
    try:
        graph = api_get(f"/graphs/{gid}/")
    except Exception as e:
        _check("Flow exists", False, str(e))
        print("\nFlow does not exist. Cannot continue.")
        sys.exit(1)
    _check("Flow exists", True, graph.get("name", ""))

    # 2. Nodes
    node_types = {
        "python": graph.get("python_node_list", []),
        "cdt": graph.get("classification_decision_table_node_list", []),
        "dt": graph.get("decision_table_node_list", []),
        "crew": graph.get("crew_node_list", []),
        "llm": graph.get("llm_node_list", []),
        "code-agent": graph.get("code_agent_node_list", []),
        "file-extractor": graph.get("file_extractor_node_list", []),
        "audio": graph.get("audio_transcription_node_list", []),
        "webhook": graph.get("webhook_trigger_node_list", []),
        "telegram": graph.get("telegram_trigger_node_list", []),
        "start": graph.get("start_node_list", []),
        "end": graph.get("end_node_list", []),
        "subgraph": graph.get("subgraph_node_list", []),
    }
    total_nodes = sum(len(v) for v in node_types.values())
    counts = ", ".join(f"{k}={len(v)}" for k, v in node_types.items() if v)
    _check("Nodes exist", total_nodes > 0, f"{total_nodes} nodes ({counts})")

    if verbose:
        for ntype, nlist in node_types.items():
            for n in nlist:
                name = n.get("node_name", "?")
                nid = n.get("id", "?")
                print(f"      {ntype:12s} id={nid:>5} {name}")

    # 3. Edges
    edges = graph.get("edge_list", [])
    _check("Edges exist", len(edges) > 0, f"{len(edges)} edges")
    if verbose:
        id_to_name = build_id_to_name_map(graph)
        for e in edges:
            src = id_to_name.get(e.get('start_node_id'), f"?#{e.get('start_node_id')}")
            tgt = id_to_name.get(e.get('end_node_id'), f"?#{e.get('end_node_id')}")
            print(f"      {src} \u2192 {tgt}")

    # 4. Node metadata (positions) — each node should have its own metadata field
    nodes_with_pos = 0
    nodes_without_pos = []
    for ntype, nlist in node_types.items():
        for n in nlist:
            meta = n.get("metadata") or {}
            if meta.get("position"):
                nodes_with_pos += 1
            else:
                nodes_without_pos.append(n.get("node_name", "?"))
    _check("Node metadata (positions)", nodes_with_pos > 0 or total_nodes == 0,
           f"{nodes_with_pos}/{total_nodes} nodes have positions" +
           (f" — missing: {', '.join(nodes_without_pos[:5])}" if nodes_without_pos else ""))

    # 5. Edge node IDs vs known node IDs
    all_node_ids = set()
    for nlist in node_types.values():
        for n in nlist:
            all_node_ids.add(n.get("id"))
    bad_edges = []
    for e in edges:
        sid = e.get('start_node_id')
        eid = e.get('end_node_id')
        if sid not in all_node_ids:
            bad_edges.append(f"unknown source id: {sid}")
        if eid not in all_node_ids:
            bad_edges.append(f"unknown target id: {eid}")
    _check("All edge endpoints are valid nodes", len(bad_edges) == 0,
           "; ".join(bad_edges[:3]) if bad_edges else "")

    # 6. CDT groups
    cdt_nodes = graph.get("classification_decision_table_node_list", [])
    for cdt in cdt_nodes:
        groups = cdt.get("condition_groups", [])
        name = cdt.get("node_name", "?")
        _check(f"CDT '{name}' has groups", len(groups) > 0, f"{len(groups)} groups")

    # 7. Python nodes have code
    for pn in graph.get("python_node_list", []):
        name = pn.get("node_name", "?")
        code = pn.get("python_code", {}).get("code", "")
        _check(f"Python '{name}' has code", len(code) > 0, f"{len(code)} chars")

    # 8. Sessions (informational)
    try:
        sessions = api_get(f"/sessions/?graph_id={gid}&limit=1")
        has_sessions = isinstance(sessions, list) and len(sessions) > 0
    except Exception:
        has_sessions = False
    print(f"  {'i'} INFO  Has session history  \u2014 {'yes' if has_sessions else 'no sessions yet'}")

    # 9. Three-way verify (optional)
    if do_verify:
        flow_dir = FLOWS_DIR / str(gid)
        if flow_dir.is_dir():
            specs = _discover_files(str(flow_dir))
            if specs:
                mismatches = 0
                for spec in specs:
                    try:
                        file_data = _read_from_file(spec)
                        db_data, node_name = _read_from_db(spec, gid)
                        if db_data is None:
                            mismatches += 1
                            if verbose:
                                print(f"      NOT IN DB: {Path(spec.path).name}")
                            continue
                        meta_data = _read_from_metadata(spec, gid, node_name)
                        if isinstance(file_data, str):
                            if file_data.strip() != (db_data or "").strip():
                                mismatches += 1
                                if verbose:
                                    print(f"      MISMATCH (file vs DB): {Path(spec.path).name}")
                            if meta_data and file_data.strip() != meta_data.strip():
                                mismatches += 1
                                if verbose:
                                    print(f"      MISMATCH (file vs metadata): {Path(spec.path).name}")
                        else:
                            fj = _canonical_json(file_data)
                            dj = _canonical_json(db_data)
                            if fj != dj:
                                mismatches += 1
                                if verbose:
                                    print(f"      MISMATCH (file vs DB): {Path(spec.path).name}")
                            if meta_data:
                                mj = _canonical_json(meta_data)
                                if fj != mj:
                                    mismatches += 1
                                    if verbose:
                                        print(f"      MISMATCH (file vs metadata): {Path(spec.path).name}")
                    except Exception as e:
                        mismatches += 1
                        if verbose:
                            print(f"      ERROR: {Path(spec.path).name}: {e}")
                _check("Local files match DB + metadata", mismatches == 0,
                       f"{mismatches} mismatches" if mismatches else f"{len(specs)} files checked")
            else:
                _check("Local files exist", False, f"no recognized files at {flow_dir}")
        else:
            _check("Local files exist", False, f"no files at {flow_dir}")

    # Summary
    print(f"\n{'='*50}")
    print(f"  Flow {gid}: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
