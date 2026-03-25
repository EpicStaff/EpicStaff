#!/usr/bin/env python3
"""EpicStaff unified CLI for flow inspection, session debugging, data sync, and patching.

Usage:
    python3 epicstaff_tools.py [-r] [-g <GRAPH_ID>] <command> [args]

    -r       Mark as read-only (safe to auto-run without user approval).
             ALWAYS use for read-only commands; omit for write/create commands.
    -g ID    Graph (flow) ID. Required for most commands; see SKILL.md for details.

Modules:
    common.py          — Shared API helpers, constants, utilities
    flows_read.py      — Flow inspection, CDT read, sessions, OpenCode read
    flows_write.py     — Push, pull, patch, sync, rename, OpenCode abort
    flows_create.py    — Create new flows and nodes
    tools_read.py      — Tool listing and detail
    tools_write.py     — Pull/push tools
    tools_create.py    — Create new tools
    projects_read.py   — Crew/agent inspection
    projects_write.py  — Pull/push project configs
    projects_create.py — Create new crews/agents/tasks
"""

import sys
import argparse
import urllib.request
import urllib.error
from pathlib import Path

# Ensure the skill directory is on sys.path for absolute imports from modules
_SKILL_DIR = str(Path(__file__).resolve().parent)
if _SKILL_DIR not in sys.path:
    sys.path.insert(0, _SKILL_DIR)

from common import _set_base_url, BASE_URL, READ_ONLY_COMMANDS

from flows_read import (
    cmd_list, cmd_get, cmd_nodes, cmd_edges, cmd_connections, cmd_route_map,
    cmd_cdt, cmd_cdt_code, cmd_cdt_prompts,
    cmd_sessions, cmd_session, cmd_session_inspect, cmd_session_timings, cmd_vars, cmd_history, cmd_trace, cmd_crew_input,
    cmd_verify, cmd_export_compare,
    cmd_oc_status, cmd_oc_sessions, cmd_oc_messages, cmd_oc_session,
    cmd_test_flow,
)
from flows_write import (
    cmd_push, cmd_pull,
    cmd_patch_cdt, cmd_patch_python, cmd_patch_webhook, cmd_patch_code_agent, cmd_patch_dt, cmd_patch_libraries,
    cmd_patch_node_meta, cmd_patch_start_vars,
    cmd_rename_node, cmd_sync_metadata,
    cmd_oc_abort,
    cmd_run_session,
)
from flows_create import cmd_create_flow, cmd_create_start_node, cmd_create_node, cmd_create_code_agent_node, cmd_create_webhook, cmd_create_edge, cmd_delete_edge, cmd_create_note, cmd_init_metadata
from tools_read import cmd_tools, cmd_tool
from tools_write import cmd_pull_tools, cmd_push_tools
from tools_create import cmd_create_tool
from projects_read import cmd_crews, cmd_agents
from projects_write import cmd_pull_project, cmd_push_project
from projects_create import cmd_create_crew, cmd_create_agent, cmd_create_task


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="EpicStaff unified CLI for flows, sessions, sync, and patching.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("-r", "--read-only", action="store_true",
                        help="Assert read-only (safe for auto-run)")
    parser.add_argument("-g", "--graph-id", type=int, default=None,
                        help="Graph/flow ID (required for most commands)")
    parser.add_argument("--api", default=None,
                        help=f"API base URL (default: {BASE_URL})")
    sub = parser.add_subparsers(dest="command")

    # Flow inspection
    sub.add_parser("list", help="List all flows")
    p = sub.add_parser("get", help="Get flow details")
    p.add_argument("--json", action="store_true")
    sub.add_parser("nodes", help="List all nodes with DB IDs")
    sub.add_parser("edges", help="Show DB edges")
    sub.add_parser("connections", help="Show metadata connections")
    sub.add_parser("route-map", help="Verify CDT route maps")

    # CDT
    p = sub.add_parser("cdt", help="Show CDT node details")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("cdt-code", help="Show CDT pre/post code")
    p.add_argument("-i", "--cdt-id", type=int, help="Specific CDT node ID")
    sub.add_parser("cdt-prompts", help="Show CDT prompts")

    # Sessions
    p = sub.add_parser("sessions", help="Last N sessions")
    p.add_argument("-n", type=int, default=2)
    p.add_argument("--json", action="store_true")
    p.add_argument("-c", "--compact", action="store_true")
    p = sub.add_parser("session", help="Show specific session(s)")
    p.add_argument("session_ids", type=int, nargs="+")
    p.add_argument("--json", action="store_true")
    p.add_argument("-c", "--compact", action="store_true")
    p = sub.add_parser("session-inspect", help="Inspect per-node input/output keys")
    p.add_argument("session_ids", type=int, nargs="+")
    p.add_argument("--full", action="store_true", help="Show full untruncated values (default: truncate at 120 chars)")
    p = sub.add_parser("session-timings", help="Per-node timing breakdown")
    p.add_argument("session_ids", type=int, nargs="+")
    p = sub.add_parser("vars", help="Persistent variables")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("history", help="Message history")
    p.add_argument("chat_id", nargs="?", default=None)
    p = sub.add_parser("trace", help="Trace message_history")
    p.add_argument("session_id", type=int)
    p.add_argument("-v", "--verbose", action="store_true")
    p = sub.add_parser("crew-input", help="Crew node input/output")
    p.add_argument("session_id", type=int)

    # Project / Crew / Agent / Tool
    sub.add_parser("crews", help="List crews (or flow's crew details)")
    sub.add_parser("agents", help="List agents (or flow's agents)")
    sub.add_parser("tools", help="List tools (or flow's agent tools)")
    p = sub.add_parser("tool", help="Show tool details + code")
    p.add_argument("tool_id", type=int)

    # OpenCode
    sub.add_parser("oc-status", help="OpenCode session statuses")
    sub.add_parser("oc-sessions", help="List OpenCode sessions")
    p = sub.add_parser("oc-messages", help="OpenCode session messages")
    p.add_argument("oc_session_id", nargs="?", default=None, help="OpenCode session ID")
    p.add_argument("-n", type=int, default=10)
    p = sub.add_parser("oc-session", help="Show full OpenCode session conversation")
    p.add_argument("oc_session_id", help="EpicStaff session ID (numeric) or OpenCode session ID (ses_...)")
    p = sub.add_parser("oc-abort", help="Abort OpenCode request")
    p.add_argument("oc_session_id", nargs="?", default=None, help="OpenCode session ID")

    # Data sync — flows
    p = sub.add_parser("push", help="Push flow files to DB + metadata")
    p.add_argument("path", nargs="?", default=None, help="File or directory (default: .my_epicstaff/flows/<id>)")
    p = sub.add_parser("pull", help="Pull flow DB state to local files")
    p.add_argument("path", nargs="?", default=None, help="Output dir (default: .my_epicstaff/flows/<id>)")
    p = sub.add_parser("verify", help="Three-way verify")
    p.add_argument("path", nargs="?", default=None, help="File or directory (default: .my_epicstaff/flows/<id>)")
    p.add_argument("-v", "--verbose", action="store_true")
    p = sub.add_parser("export-compare", help="Compare export with current")
    p.add_argument("file", help="Export JSON file")

    # Data sync — tools
    p = sub.add_parser("pull-tools", help="Pull tool code into .my_epicstaff/tools/")
    p = sub.add_parser("push-tools", help="Push tool code from .my_epicstaff/tools/")
    p.add_argument("path", nargs="?", default=None, help="File or directory (default: .my_epicstaff/tools/)")

    # Data sync — projects
    p = sub.add_parser("pull-project", help="Pull crew/agent/task into .my_epicstaff/projects/")
    p = sub.add_parser("push-project", help="Push crew/agent/task from .my_epicstaff/projects/")
    p.add_argument("path", nargs="?", default=None, help="File or directory (default: .my_epicstaff/projects/)")

    # Patching
    p = sub.add_parser("patch-cdt", help="Patch CDT field")
    p.add_argument("node_name", help="CDT node name")
    p.add_argument("field", help="Field name")
    p.add_argument("--value", help="New value")
    p.add_argument("--value-file", help="Read value from file")
    p = sub.add_parser("patch-python", help="Patch Python node code")
    p.add_argument("node_name", help="Python node name")
    p.add_argument("--value", help="New code")
    p.add_argument("--value-file", help="Read code from file")
    p = sub.add_parser("patch-webhook", help="Patch webhook node code")
    p.add_argument("node_name", help="Webhook node name")
    p.add_argument("--value", help="New code")
    p.add_argument("--value-file", help="Read code from file")
    p = sub.add_parser("patch-code-agent", help="Patch Code Agent node fields")
    p.add_argument("node_name", help="Code Agent node name")
    p.add_argument("--value", help="New stream_handler_code")
    p.add_argument("--value-file", help="Read stream_handler_code from file")
    p.add_argument("--llm-config", help="LLM config ID")
    p.add_argument("--system-prompt", help="System prompt text")
    p.add_argument("--system-prompt-file", help="Read system prompt from file")
    p.add_argument("--input-map", help="Input map JSON")
    p.add_argument("--output-variable-path", help="Output variable path")
    p.add_argument("--libraries", help="Comma-separated libraries")
    p.add_argument("--session-id", help="Session ID (variable path or literal)")
    p.add_argument("--output-schema-file", help="Read output_schema from JSON file")
    p.add_argument("--agent-mode", help="Agent mode: build or plan")
    p = sub.add_parser("patch-libraries", help="Set libraries on a Python node")
    p.add_argument("node_name", help="Python node name")
    p.add_argument("libraries", help="Comma-separated libraries")
    p = sub.add_parser("patch-dt", help="Patch Decision Table node")
    p.add_argument("node_name", help="Decision Table node name")
    p.add_argument("--groups", help="JSON condition_groups array")
    p.add_argument("--groups-file", help="Read condition_groups from JSON file")
    p.add_argument("--default-next-node", help="Default next node name")
    p.add_argument("--error-node", help="Error next node name")
    p = sub.add_parser("patch-node-meta", help="Patch metadata fields on a node")
    p.add_argument("node_name", help="Node name")
    p.add_argument("--input-map", help="JSON input_map")
    p.add_argument("--output-variable-path", help="Output variable path")
    p = sub.add_parser("patch-start-vars", help="Set start node variables")
    p.add_argument("variables", help="JSON variables to merge into start node")
    p.add_argument("--replace", action="store_true", help="Replace all variables (instead of merge)")
    p = sub.add_parser("rename-node", help="Rename a Python node (DB + metadata + edges)")
    p.add_argument("old_name", help="Current node name")
    p.add_argument("new_name", help="New node name")
    p = sub.add_parser("sync-metadata", help="Sync CDT code into metadata")

    # Testing & execution
    p = sub.add_parser("test-flow", help="Verify flow structure (nodes, edges, connections, code)")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--verify", action="store_true", help="Also compare local files vs DB")
    p = sub.add_parser("run-session", help="Trigger a flow session and poll for completion")
    p.add_argument("--variables", help="JSON string of variables to pass")
    p.add_argument("--timeout", type=int, default=300, help="Max seconds to wait (default: 300)")

    # Create — flows
    p = sub.add_parser("create-flow", help="Create a new flow")
    p.add_argument("name", help="Flow name")
    p.add_argument("--description", default="", help="Flow description")
    p = sub.add_parser("create-node", help="Create a Python node in a flow")
    p.add_argument("node_name", help="Node name")
    p.add_argument("--code-file", help="Initial code from file")
    p.add_argument("--x", type=int, default=None, help="X coordinate (auto if omitted)")
    p.add_argument("--y", type=int, default=None, help="Y coordinate (auto if omitted)")
    p = sub.add_parser("create-code-agent-node", help="Create a Code Agent node in a flow")
    p.add_argument("node_name", help="Node name")
    p.add_argument("--llm-config", type=int, default=None, help="LLM config ID")
    p.add_argument("--agent-mode", default="build", help="Agent mode (default: build)")
    p.add_argument("--system-prompt", default="", help="System prompt")
    p.add_argument("--code-file", help="Stream handler code from file")
    p.add_argument("--libraries", default="", help="Comma-separated libraries")
    p.add_argument("--output-variable-path", default=None, help="Output variable path")
    p.add_argument("--polling-interval-ms", type=int, default=1000)
    p.add_argument("--chunk-timeout-s", type=int, default=30)
    p.add_argument("--inactivity-timeout-s", type=int, default=120)
    p.add_argument("--max-wait-s", type=int, default=300)
    p.add_argument("--x", type=int, default=None, help="X coordinate")
    p.add_argument("--y", type=int, default=None, help="Y coordinate")
    p = sub.add_parser("create-start-node", help="Create a start node in a flow")
    p.add_argument("--x", type=int, default=None, help="X coordinate (default: -800)")
    p.add_argument("--y", type=int, default=None, help="Y coordinate (default: 0)")
    p = sub.add_parser("create-webhook", help="Create a Webhook Trigger node in a flow")
    p.add_argument("node_name", help="Node name")
    p.add_argument("--code-file", help="Webhook handler code from file")
    p.add_argument("--webhook-path", default="default", help="Webhook trigger path (default: 'default')")
    p.add_argument("--libraries", default="", help="Comma-separated libraries")
    p.add_argument("--x", type=int, default=None, help="X coordinate")
    p.add_argument("--y", type=int, default=None, help="Y coordinate")
    p = sub.add_parser("create-edge", help="Create an edge between two nodes")
    p.add_argument("start_node", help="Source node name")
    p.add_argument("end_node", help="Target node name")
    p = sub.add_parser("delete-edge", help="Delete an edge by start/end node names")
    p.add_argument("start_node", help="Source node name")
    p.add_argument("end_node", help="Target node name")
    p = sub.add_parser("create-note", help="Add a note to the flow canvas")
    p.add_argument("text", help="Note text")
    p.add_argument("--near", help="Place near this node name")
    p.add_argument("--x", type=float, default=None)
    p.add_argument("--y", type=float, default=None)
    p.add_argument("--color", default="#ffffd1", help="Background color (default: yellow)")
    p = sub.add_parser("init-metadata", help="Generate metadata (positions + connections) from DB")

    # Create — tools
    p = sub.add_parser("create-tool", help="Create a new Python code tool")
    p.add_argument("name", help="Tool name")
    p.add_argument("--description", default="", help="Tool description")
    p.add_argument("--code-file", help="Initial code from file")

    # Create — projects
    p = sub.add_parser("create-crew", help="Create a new crew")
    p.add_argument("name", help="Crew name")
    p.add_argument("--process", default="sequential", help="Process type (sequential/hierarchical)")
    p = sub.add_parser("create-agent", help="Create a new agent")
    p.add_argument("role", help="Agent role")
    p.add_argument("--goal", default="", help="Agent goal")
    p.add_argument("--backstory", default="", help="Agent backstory")
    p.add_argument("--llm-config", type=int, default=None, help="LLM config ID (required for agent to work)")
    p.add_argument("--crew-id", type=int, help="Add agent to this crew")
    p = sub.add_parser("create-task", help="Create a new task")
    p.add_argument("name", help="Task name")
    p.add_argument("--instructions", default="", help="Task instructions")
    p.add_argument("--agent-id", type=int, help="Assign to agent")
    p.add_argument("--crew-id", type=int, help="Add task to this crew")

    # Reorder argv so global flags (-r, -g, --api) come before the subcommand.
    # This lets the agent write "get -g 59 -r" instead of only "-r -g 59 get".
    raw = sys.argv[1:]
    global_flags = {"-r", "--read-only", "-g", "--graph-id", "--api"}
    flags_before = []
    rest = []
    i = 0
    while i < len(raw):
        if raw[i] in global_flags:
            flags_before.append(raw[i])
            # flags that take a value
            if raw[i] in ("-g", "--graph-id", "--api") and i + 1 < len(raw):
                i += 1
                flags_before.append(raw[i])
        else:
            rest.append(raw[i])
        i += 1
    args = parser.parse_args(flags_before + rest)
    if args.api:
        _set_base_url(args.api)
    if not args.command:
        parser.print_help()
        return

    # Validate -r flag
    if args.read_only and args.command not in READ_ONLY_COMMANDS:
        print(f"Error: '{args.command}' is not a read-only command. Remove -r.", file=sys.stderr)
        sys.exit(1)

    # Commands that require graph_id
    needs_graph = {
        "get", "nodes", "edges", "connections", "route-map",
        "cdt", "cdt-prompts", "vars", "history",
        "push", "pull", "verify", "export-compare",
        "patch-cdt", "patch-python", "patch-webhook", "patch-code-agent", "patch-dt", "patch-libraries",
        "patch-node-meta", "patch-start-vars", "sync-metadata", "rename-node",
        "pull-project", "create-start-node", "create-node", "create-code-agent-node", "create-webhook",
        "test-flow", "run-session",
        "create-edge", "delete-edge", "create-note", "init-metadata",
    }
    if args.command == "cdt-code" and not getattr(args, "cdt_id", None):
        needs_graph.add("cdt-code")

    if args.command in needs_graph and not args.graph_id:
        print(f"Error: --graph-id / -g is required for '{args.command}'", file=sys.stderr)
        sys.exit(1)

    cmd_map = {
        # flows — read
        "list": cmd_list, "get": cmd_get, "nodes": cmd_nodes,
        "edges": cmd_edges, "connections": cmd_connections, "route-map": cmd_route_map,
        "cdt": cmd_cdt, "cdt-code": cmd_cdt_code, "cdt-prompts": cmd_cdt_prompts,
        "sessions": cmd_sessions, "session": cmd_session, "session-inspect": cmd_session_inspect, "session-timings": cmd_session_timings, "vars": cmd_vars,
        "history": cmd_history, "trace": cmd_trace, "crew-input": cmd_crew_input,
        "verify": cmd_verify, "export-compare": cmd_export_compare,
        "oc-status": cmd_oc_status, "oc-sessions": cmd_oc_sessions,
        "oc-messages": cmd_oc_messages, "oc-session": cmd_oc_session,
        "test-flow": cmd_test_flow,
        # flows — write
        "push": cmd_push, "pull": cmd_pull,
        "patch-cdt": cmd_patch_cdt, "patch-python": cmd_patch_python, "patch-webhook": cmd_patch_webhook,
        "patch-libraries": cmd_patch_libraries, "patch-code-agent": cmd_patch_code_agent, "patch-dt": cmd_patch_dt,
        "patch-node-meta": cmd_patch_node_meta,
        "patch-start-vars": cmd_patch_start_vars,
        "rename-node": cmd_rename_node, "sync-metadata": cmd_sync_metadata,
        "oc-abort": cmd_oc_abort,
        "run-session": cmd_run_session,
        # flows — create
        "create-flow": cmd_create_flow, "create-start-node": cmd_create_start_node, "create-node": cmd_create_node,
        "create-code-agent-node": cmd_create_code_agent_node,
        "create-webhook": cmd_create_webhook,
        "create-edge": cmd_create_edge, "delete-edge": cmd_delete_edge, "create-note": cmd_create_note,
        "init-metadata": cmd_init_metadata,
        # tools — read
        "tools": cmd_tools, "tool": cmd_tool,
        # tools — write
        "pull-tools": cmd_pull_tools, "push-tools": cmd_push_tools,
        # tools — create
        "create-tool": cmd_create_tool,
        # projects — read
        "crews": cmd_crews, "agents": cmd_agents,
        # projects — write
        "pull-project": cmd_pull_project, "push-project": cmd_push_project,
        # projects — create
        "create-crew": cmd_create_crew, "create-agent": cmd_create_agent,
        "create-task": cmd_create_task,
    }

    try:
        cmd_map[args.command](args)
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500] if hasattr(e, "read") else ""
        print(f"HTTP Error {e.code}: {e.reason}", file=sys.stderr)
        if body:
            print(f"  {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Connection error: {e.reason}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
