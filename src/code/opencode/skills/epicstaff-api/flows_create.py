"""Flow create operations — create new flows, nodes, edges, and metadata."""

import sys
import json

from common import api_get, api_post, api_patch, api_delete, _get_graph, build_id_to_name_map, resolve_node_id

# Vertical gap between stacked nodes
_NODE_STACK_GAP = 60


def _collect_all_node_positions(graph):
    """Collect position info from all nodes' own metadata fields.

    Returns a list of dicts with 'position' key, matching the format
    _auto_position expects.
    """
    result = []
    for list_key in (
        "start_node_list", "end_node_list", "python_node_list", "crew_node_list",
        "code_agent_node_list", "llm_node_list", "file_extractor_node_list",
        "audio_transcription_node_list", "webhook_trigger_node_list",
        "telegram_trigger_node_list", "decision_table_node_list",
        "classification_decision_table_node_list", "note_node_list",
        "subgraph_node_list",
    ):
        for n in graph.get(list_key, []):
            meta = n.get("metadata") or {}
            pos = meta.get("position")
            if pos:
                result.append({"position": pos})
    return result


def _auto_position(existing_nodes, x=None, y=None):
    """Compute position for a new node.

    If x/y are provided, use them directly.
    Otherwise, place below the lowest node at the rightmost x position
    (i.e. append to the last logical step).
    """
    if x is not None and y is not None:
        return {"x": x, "y": y}

    if not existing_nodes:
        return {"x": 0, "y": 0}

    positions = []
    for n in existing_nodes:
        pos = n.get("position", {})
        px, py = pos.get("x"), pos.get("y")
        if px is not None and py is not None:
            positions.append((px, py))

    if not positions:
        return {"x": 0, "y": 0}

    if x is not None:
        # x given, auto y: stack below lowest node at that x
        same_x = [py for px, py in positions if abs(px - x) < 50]
        if same_x:
            return {"x": x, "y": max(same_x) + _NODE_STACK_GAP}
        return {"x": x, "y": 0}

    if y is not None:
        # y given, auto x: place at rightmost x
        max_x = max(px for px, _ in positions)
        return {"x": max_x, "y": y}

    # Both auto: stack below lowest node at the rightmost x column
    max_x = max(px for px, _ in positions)
    same_col = [py for px, py in positions if abs(px - max_x) < 50]
    max_y = max(same_col) if same_col else 0
    return {"x": max_x, "y": max_y + _NODE_STACK_GAP}


def cmd_create_flow(args):
    """Create a new flow (graph) with a start node."""
    payload = {
        "name": args.name,
        "description": getattr(args, "description", ""),
    }
    result = api_post("/graphs/", payload)
    gid = result.get("id")
    print(f"Created flow: [{gid}] {result.get('name')}")

    # Create a start node (every flow needs one)
    start_payload = {
        "node_name": "__start__",
        "graph": gid,
        "variables": {"$schema": "start"},
        "metadata": {},
    }
    start_result = api_post("/startnodes/", start_payload)
    start_id = start_result.get("id")
    print(f"  Created start node (id={start_id})")

    # Set position on start node's own metadata field
    start_meta = {
        "position": {"x": -400, "y": 0},
        "color": "#d3d3d3",
        "icon": "ti ti-player-play-filled",
        "size": {"width": 125, "height": 60},
        "parentId": None,
    }
    api_patch(f"/startnodes/{start_id}/", {"metadata": start_meta})
    print(f"  Node metadata initialized.")
    return result


def cmd_create_start_node(args):
    """Create a start node in a flow (every flow needs one)."""
    graph_id = args.graph_id

    start_payload = {
        "node_name": "__start__",
        "graph": graph_id,
        "variables": {"$schema": "start"},
        "metadata": {},
    }
    result = api_post("/startnodes/", start_payload)
    start_id = result.get("id")
    print(f"Created start node (id={start_id}) in flow {graph_id}")

    # Set position on start node's own metadata field
    x = getattr(args, "x", None) if getattr(args, "x", None) is not None else -800
    y = getattr(args, "y", None) if getattr(args, "y", None) is not None else 0
    start_meta = {
        "position": {"x": x, "y": y},
        "color": "#d3d3d3",
        "icon": "ti ti-player-play-filled",
        "size": {"width": 125, "height": 60},
        "parentId": None,
    }
    api_patch(f"/startnodes/{start_id}/", {"metadata": start_meta})
    print(f"  Position: x={x}, y={y}")
    print(f"  Node metadata set.")
    return result


def cmd_create_node(args):
    """Create a Python node in a flow."""
    graph_id = args.graph_id
    node_name = args.node_name
    code = ""
    if getattr(args, "code_file", None):
        with open(args.code_file) as f:
            code = f.read()

    payload = {
        "node_name": node_name,
        "graph": graph_id,
        "python_code": {"code": code, "libraries": []},
        "metadata": {},
    }
    result = api_post("/pythonnodes/", payload)
    node_id = result.get("id")
    print(f"Created Python node '{node_name}' (id={node_id}) in flow {graph_id}")

    # Set position on node's own metadata field
    graph = _get_graph(graph_id)
    all_nodes = _collect_all_node_positions(graph)
    position = _auto_position(all_nodes, x=getattr(args, "x", None), y=getattr(args, "y", None))
    node_meta = {
        "position": position,
        "color": _NODE_DEFAULTS["python"]["color"],
        "icon": _NODE_DEFAULTS["python"]["icon"],
        "size": _NODE_DEFAULTS["python"]["size"],
        "parentId": None,
    }
    api_patch(f"/pythonnodes/{node_id}/", {"metadata": node_meta})
    print(f"  Position: x={position['x']}, y={position['y']}")
    return result


def cmd_create_code_agent_node(args):
    """Create a Code Agent node in a flow."""
    graph_id = args.graph_id
    node_name = args.node_name

    stream_handler_code = ""
    if getattr(args, "code_file", None):
        with open(args.code_file) as f:
            stream_handler_code = f.read()

    libraries = []
    if getattr(args, "libraries", None):
        libraries = [lib.strip() for lib in args.libraries.split(",") if lib.strip()]

    payload = {
        "node_name": node_name,
        "graph": graph_id,
        "agent_mode": getattr(args, "agent_mode", None) or "build",
        "system_prompt": getattr(args, "system_prompt", None) or "",
        "stream_handler_code": stream_handler_code,
        "libraries": libraries,
        "polling_interval_ms": getattr(args, "polling_interval_ms", None) or 1000,
        "chunk_timeout_s": getattr(args, "chunk_timeout_s", None) or 30,
        "inactivity_timeout_s": getattr(args, "inactivity_timeout_s", None) or 120,
        "max_wait_s": getattr(args, "max_wait_s", None) or 300,
        "input_map": {},
        "output_variable_path": getattr(args, "output_variable_path", None),
        "metadata": {},
    }

    # LLM config
    llm_config_id = getattr(args, "llm_config", None)
    if llm_config_id:
        payload["llm_config"] = int(llm_config_id)

    result = api_post("/code-agent-nodes/", payload)
    node_id = result.get("id")
    print(f"Created Code Agent node '{node_name}' (id={node_id}) in flow {graph_id}")

    # Set position on node's own metadata field
    graph = _get_graph(graph_id)
    all_nodes = _collect_all_node_positions(graph)
    position = _auto_position(all_nodes, x=getattr(args, "x", None), y=getattr(args, "y", None))
    node_meta = {
        "position": position,
        "color": _NODE_DEFAULTS["code-agent"]["color"],
        "icon": _NODE_DEFAULTS["code-agent"]["icon"],
        "size": _NODE_DEFAULTS["code-agent"]["size"],
        "parentId": None,
    }
    api_patch(f"/code-agent-nodes/{node_id}/", {"metadata": node_meta})
    print(f"  Position: x={position['x']}, y={position['y']}")
    print(f"  Agent mode: {payload['agent_mode']}")
    if llm_config_id:
        print(f"  LLM config: {llm_config_id}")
    return result


def cmd_create_webhook(args):
    """Create a Webhook Trigger node in a flow."""
    graph_id = args.graph_id
    node_name = args.node_name
    code = ""
    if getattr(args, "code_file", None):
        with open(args.code_file) as f:
            code = f.read()

    libraries = []
    if getattr(args, "libraries", None):
        libraries = [lib.strip() for lib in args.libraries.split(",") if lib.strip()]

    webhook_path = getattr(args, "webhook_path", None) or "default"

    payload = {
        "node_name": node_name,
        "graph": graph_id,
        "python_code": {"code": code, "libraries": libraries},
        "webhook_trigger_path": webhook_path,
        "metadata": {},
    }
    result = api_post("/webhook-trigger-nodes/", payload)
    node_id = result.get("id")
    print(f"Created Webhook node '{node_name}' (id={node_id}) in flow {graph_id}")
    print(f"  webhook_trigger_path: {webhook_path}")

    # Set position on node's own metadata field
    graph = _get_graph(graph_id)
    all_nodes = _collect_all_node_positions(graph)
    position = _auto_position(all_nodes, x=getattr(args, "x", None), y=getattr(args, "y", None))
    node_meta = {
        "position": position,
        "color": _NODE_DEFAULTS["webhook-trigger"]["color"],
        "icon": _NODE_DEFAULTS["webhook-trigger"]["icon"],
        "size": _NODE_DEFAULTS["webhook-trigger"]["size"],
        "parentId": None,
    }
    api_patch(f"/webhook-trigger-nodes/{node_id}/", {"metadata": node_meta})
    print(f"  Position: x={position['x']}, y={position['y']}")
    return result


def cmd_create_note(args):
    """Add a note to a flow's canvas (NoteNode DB record + metadata)."""
    graph_id = args.graph_id
    text = args.text
    graph = api_get(f"/graphs/{graph_id}/")

    # Position near a target node if specified, otherwise auto-place
    near = getattr(args, "near", None)
    x = getattr(args, "x", None)
    y = getattr(args, "y", None)

    if near:
        # Scan all node types for a matching name to read position
        for list_key in _NODE_TYPE_ENDPOINTS:
            for n in graph.get(list_key, []):
                if n.get("node_name", "").lower() == near.lower():
                    pos = (n.get("metadata") or {}).get("position", {})
                    x = x if x is not None else pos.get("x", 0)
                    y = y if y is not None else pos.get("y", 0) + 120
                    break

    if x is None:
        x = 0
    if y is None:
        y = 300

    bg_color = getattr(args, "color", "#ffffd1") or "#ffffd1"

    # Auto-name: Note (#N)
    existing_notes = graph.get("note_node_list", [])
    note_num = len(existing_notes) + 1
    node_name = f"Note (#{note_num})"

    # Create NoteNode in DB
    payload = {
        "node_name": node_name,
        "graph": graph_id,
        "content": text,
        "metadata": {
            "position": {"x": x, "y": y},
            "color": _NODE_DEFAULTS["note"]["color"],
            "icon": _NODE_DEFAULTS["note"]["icon"],
            "size": _NODE_DEFAULTS["note"]["size"],
            "parentId": None,
            "backgroundColor": bg_color,
        },
    }
    result = api_post("/note-nodes/", payload)
    note_id = result.get("id")
    print(f"Created {node_name} (id={note_id}) at x={x}, y={y}")
    print(f"  Text: {text[:80]}{'...' if len(text) > 80 else ''}")
    return result


def cmd_delete_edge(args):
    """Delete an edge between two nodes in a flow."""
    graph_id = args.graph_id
    graph = _get_graph(graph_id)
    start_id = resolve_node_id(args.start_node, graph)
    end_id = resolve_node_id(args.end_node, graph)
    edges = graph.get("edge_list", [])
    for e in edges:
        if e.get("start_node_id") == start_id and e.get("end_node_id") == end_id:
            api_delete(f"/edges/{e['id']}/")
            print(f"Deleted edge {e['id']}: {args.start_node} → {args.end_node}")
            return
    print(f"Edge {args.start_node} → {args.end_node} not found in flow {graph_id}", file=sys.stderr)
    sys.exit(1)


def cmd_create_edge(args):
    """Create an edge between two nodes in a flow."""
    graph_id = args.graph_id
    graph = _get_graph(graph_id)
    start_id = resolve_node_id(args.start_node, graph)
    end_id = resolve_node_id(args.end_node, graph)
    result = api_post("/edges/", {
        "start_node_id": start_id,
        "end_node_id": end_id,
        "graph": graph_id,
    })
    eid = result.get("id")
    print(f"Created edge {eid}: {args.start_node} \u2192 {args.end_node} ({start_id}\u2192{end_id})")
    return result


# UI rendering defaults per node type
_NODE_DEFAULTS = {
    "start": {
        "icon": "ti ti-player-play-filled",
        "size": {"width": 125, "height": 60},
        "color": "#d3d3d3",
    },
    "end": {
        "icon": "ti ti-player-stop-filled",
        "size": {"width": 125, "height": 60},
        "color": "#ef4444",
    },
    "python": {
        "icon": "ti ti-brand-python",
        "size": {"width": 330, "height": 60},
        "color": "#ffcf3f",
    },
    "webhook-trigger": {
        "icon": "ti ti-world",
        "size": {"width": 330, "height": 60},
        "color": "#21f367ff",
    },
    "telegram-trigger": {
        "icon": "ti ti-brand-telegram",
        "size": {"width": 330, "height": 60},
        "color": "#2aabee",
    },
    "classification-decision-table": {
        "icon": "ti ti-table",
        "size": {"width": 330, "height": 60},
        "color": "#a78bfa",
    },
    "table": {
        "icon": "ti ti-table",
        "size": {"width": 330, "height": 60},
        "color": "#00aaff",
    },
    "project": {
        "icon": "ti ti-users",
        "size": {"width": 330, "height": 60},
        "color": "#60a5fa",
    },
    "code-agent": {
        "icon": "ti ti-terminal-2",
        "size": {"width": 330, "height": 60},
        "color": "#00e676",
    },
    "llm": {
        "icon": "ti ti-brain",
        "size": {"width": 330, "height": 60},
        "color": "#f472b6",
    },
    "file-extractor": {
        "icon": "ti ti-file-text",
        "size": {"width": 330, "height": 60},
        "color": "#fb923c",
    },
    "audio": {
        "icon": "ti ti-microphone",
        "size": {"width": 330, "height": 60},
        "color": "#38bdf8",
    },
    "note": {
        "icon": "ti ti-note",
        "size": {"width": 250, "height": 120},
        "color": "#fbbf24",
    },
    "subgraph": {
        "icon": "ti ti-hierarchy-2",
        "size": {"width": 330, "height": 60},
        "color": "#c084fc",
    },
}

# Map node list keys to their PATCH API endpoints
_NODE_TYPE_ENDPOINTS = {
    "start_node_list": "/startnodes/",
    "end_node_list": "/endnodes/",
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
    "note_node_list": "/note-nodes/",
    "subgraph_node_list": "/subgraph-nodes/",
}



def cmd_init_metadata(args):
    """Set UI positions on each node's own metadata field.

    Post-RC, Graph.metadata is no longer used. The frontend reads
    position/color/icon/size from each node's individual `metadata`
    JSONField and derives connections from DB edges at load time.

    This command assigns auto-layout positions and PATCHes each
    node's metadata field via its type-specific API endpoint.
    """
    graph_id = args.graph_id
    graph = api_get(f"/graphs/{graph_id}/")

    # Collect all nodes: (list_key, meta_type, endpoint)
    type_lists = [
        ("start_node_list", "start"),
        ("end_node_list", "end"),
        ("python_node_list", "python"),
        ("webhook_trigger_node_list", "webhook-trigger"),
        ("telegram_trigger_node_list", "telegram-trigger"),
        ("classification_decision_table_node_list", "classification-decision-table"),
        ("decision_table_node_list", "table"),
        ("crew_node_list", "project"),
        ("code_agent_node_list", "code-agent"),
        ("llm_node_list", "llm"),
        ("file_extractor_node_list", "file-extractor"),
        ("audio_transcription_node_list", "audio"),
        ("note_node_list", "note"),
        ("subgraph_node_list", "subgraph"),
    ]

    # node_info: name -> {type, db_node, list_key}
    node_info = {}
    for list_key, meta_type in type_lists:
        for n in graph.get(list_key, []):
            name = n.get("node_name", "")
            node_info[name] = {"type": meta_type, "db_node": n, "list_key": list_key}

    if not node_info:
        print("No nodes found in flow.")
        return

    # Auto-layout: arrange nodes left-to-right following edge order
    edges = graph.get("edge_list", [])
    placed = {}
    step_x = -400
    step_gap = 400

    # Build id->name map for edge traversal
    id_to_name = {info["db_node"]["id"]: name for name, info in node_info.items()}

    # BFS-ish: start from nodes that have no incoming edges
    targets = {id_to_name.get(e.get("end_node_id")) for e in edges}
    roots = [n for n in node_info if n not in targets or n == "__start__"]

    trigger_types = {"webhook-trigger", "telegram-trigger"}
    trigger_roots = [n for n in roots if n != "__start__" and node_info[n]["type"] in trigger_types]
    other_roots = [n for n in roots if n != "__start__" and node_info[n]["type"] not in trigger_types]

    y_slot = 0
    if "__start__" in node_info:
        placed["__start__"] = {"x": step_x, "y": 0}
        y_slot = 1
    for name in trigger_roots:
        placed[name] = {"x": step_x, "y": y_slot * _NODE_STACK_GAP}
        y_slot += 1
    for i, name in enumerate(other_roots):
        root_x = step_x + step_gap if ("__start__" in node_info or trigger_roots) else step_x
        placed[name] = {"x": root_x, "y": i * _NODE_STACK_GAP}

    # Walk edges to place remaining nodes
    remaining = [n for n in node_info if n not in placed and n != "__end__"]
    for _ in range(10):
        if not remaining:
            break
        for e in edges:
            src = id_to_name.get(e.get("start_node_id"))
            tgt = id_to_name.get(e.get("end_node_id"))
            if not src or not tgt or tgt == "__end__":
                continue
            if src in placed and tgt not in placed and tgt in node_info:
                src_x = placed[src]["x"]
                same_step = [n for n, p in placed.items() if p["x"] == src_x + step_gap]
                y = len(same_step) * _NODE_STACK_GAP
                placed[tgt] = {"x": src_x + step_gap, "y": y}
        remaining = [n for n in node_info if n not in placed and n != "__end__"]

    # Place any still unplaced nodes
    max_x = max((p["x"] for p in placed.values()), default=0)
    for name in remaining:
        max_x += step_gap
        placed[name] = {"x": max_x, "y": 0}

    # PATCH each node's own metadata field with position/color/icon/size
    patched = 0
    for name, info in node_info.items():
        pos = placed.get(name, {"x": 0, "y": 0})
        defaults = _NODE_DEFAULTS.get(info["type"], _NODE_DEFAULTS["python"])
        endpoint = _NODE_TYPE_ENDPOINTS.get(info["list_key"])
        if not endpoint:
            print(f"  ⚠ No endpoint for {info['list_key']}, skipping {name}")
            continue
        node_id = info["db_node"]["id"]
        # Preserve any existing metadata fields, overlay position/color/icon/size
        existing_meta = info["db_node"].get("metadata") or {}
        node_meta = {
            **existing_meta,
            "position": pos,
            "color": defaults["color"],
            "icon": defaults["icon"],
            "size": defaults["size"],
            "parentId": None,
        }
        api_patch(f"{endpoint}{node_id}/", {"metadata": node_meta})
        patched += 1
        print(f"  {info['type']:30s} {name:30s} x={pos['x']:>6} y={pos['y']:>6}  (id={node_id})")

    print(f"\nInitialized metadata on {patched} nodes in flow {graph_id}.")
