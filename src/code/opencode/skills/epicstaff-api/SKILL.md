---
id: epicstaff
name: EpicStaff Flow Management
version: 3.10
trigger: always_on
triggers: [epicstaff, epic-staff, flows, sessions]
scope: [api, cli, integration]
description: EpicStaff flow management — inspecting, debugging, syncing, and patching flows and sessions via the epicstaff_tools.py CLI. Use this skill whenever working with EpicStaff flows, nodes, edges, connections, DTs, CDTs, sessions, crews, agents, tasks, tools, or OpenCode.
---

# EpicStaff Flow Management Skill

## Primary Tool

Use `epicstaff_tools.py` for all flow and session operations. The CLI handles DB operations, error handling, and correct serialization — things that break silently when done via raw HTTP calls.

Do not write raw `urllib`, `requests`, `curl`, or ad-hoc scripts against the Django API. The CLI exists because the API has subtle requirements (e.g., PATCH python_code without `libraries` wipes them; agent `tool_ids` PATCH is destructive replace). These are easy to get wrong in one-off scripts.

**When you need data:**
1. CLI command exists → use it
2. No command exists → add it to `epicstaff_tools.py` first, then use the CLI

### File Structure

```
epicstaff_tools.py   — CLI entry point (thin dispatcher)
common.py            — Shared API helpers, constants
flows_read.py        — Flow inspection, CDT read, sessions, OpenCode read
flows_write.py       — Push, pull, patch, sync, rename, OpenCode abort
flows_create.py      — Create new flows and nodes
tools_read.py        — Tool listing and detail
tools_write.py       — Pull/push tools
tools_create.py      — Create new tools
projects_read.py     — Crew/agent inspection
projects_write.py    — Pull/push project configs
projects_create.py   — Create new crews/agents/tasks
```

### The `-r` Flag (Read-Only)

The `-r` flag marks a command as safe to auto-run without user approval. Without it, every command blocks waiting for the user to click "approve" — which makes multi-step debugging tedious.

Read-only commands: `list`, `get`, `nodes`, `edges`, `connections`, `route-map`, `cdt`, `cdt-code`, `cdt-prompts`, `sessions`, `session`, `session-inspect`, `session-timings`, `vars`, `history`, `trace`, `crew-input`, `crews`, `agents`, `tools`, `tool`, `oc-status`, `oc-sessions`, `oc-messages`, `verify`, `export-compare`, `test-flow`.

Write commands (`push`, `pull`, `patch-*`, `sync-metadata`, `oc-abort`, `run-session`) and create commands (`create-*`) require user approval — do not use `-r`.

### The `-g <GRAPH_ID>` Flag

Most commands need a graph ID. Those that don't: `list`, `sessions` (optional -g), `session`, `session-inspect`, `session-timings`, `crews` (global), `agents` (global), `tools` (global), `tool`, `crew-input`, `oc-status`, `oc-sessions`, `oc-messages`, `oc-abort`, `create-flow`, `create-tool`, `create-crew`, `create-agent`, `create-task`, `push-tools`, `push-project`.

Exception: `cdt-code` skips `-g` when `--cdt-id` is provided.

### Local Backups: `.my_epicstaff/`

Pull/push workflow uses this directory as the local working copy:
- `.my_epicstaff/flows/<flow_id>/` — CDT code, condition groups, prompts, Python node code
- `.my_epicstaff/tools/<flow_id>/` — tool code + metadata
- `.my_epicstaff/projects/<flow_id>/` — crew, agent, task configs

Safety workflow: `pull` → edit locally → `verify` → `push` or `patch-*` → `test-flow`.

**File naming:**
- `cdt_<slug>_pre.py` / `cdt_<slug>_post.py` — CDT computation code
- `cdt_<slug>_groups.json` / `cdt_<slug>_prompts.json` — CDT config
- `node_<slug>.py` — Python node code
- `webhook_<slug>.py` — Webhook node code

### Configuration (.env)

Colocated with `epicstaff_tools.py`. Environment variables override `.env`:
- `DJANGO_PORT` (default: 8000), `OPENCODE_PORT` (default: 4096)
- `API_BASE_URL` — full override (e.g. `http://django_app:8000/api` inside Docker)

The tool resolves `.my_epicstaff/` at the repo root (3 levels up from the skill directory).

---

## Architecture Essentials

### Two Data Stores

EpicStaff has two data stores that must stay in sync:
1. **DB** (Django models) — the crew runtime reads from here
2. **Metadata** (`Graph.metadata` JSON) — the frontend reads/writes here

The `push` and `patch-*` CLI commands update both automatically. This is the main reason to always use the CLI — a raw API PATCH to a Django model won't update metadata, leaving the frontend out of sync.

### DT/CDT Routing Uses Metadata Connections

`_build_route_maps` (in `session_manager_service.py`) builds the route map from **metadata connections**, matching DB `node_name` against metadata `node_name` to find UUIDs. If the names don't match, routing fails silently. DB edges only handle non-DT routing. Both Decision Table (DT) and Classification Decision Table (CDT) nodes use this mechanism.

### Output Variables

Node output is written to variables.<subvariable> — the output_variable_path field on each node determines which subvariable. The **Start node** in the flow designer shows all available variables.* subvariables, making it the reference for what data is available to downstream nodes via input_map.

### Python Node Code Convention

Python nodes and Webhook nodes require a `def main(...)` entrypoint. The crew executor calls `main()` at runtime — code without it fails with `name 'main' is not defined`.

**Python nodes:** `main()` receives keyword arguments matching the node's `input_map` keys. It must return a dict that gets written to the node's `output_variable_path`.

```python
def main(city="Unknown", units="celsius"):
    weather = {"city": city, "temperature": 18.5, "conditions": "partly cloudy"}
    return {"weather_data": weather}
```

**Webhook nodes:** `main()` receives the full trigger payload dict.

```python
def main(trigger_payload=None):
    body = trigger_payload.get("body", {})
    city = body.get("city")
    if not city:
        return {"error": "Missing 'city' field", "status": 400}
    return {"city": city}
```

The CLI warns if pushed/patched code is missing `def main(`. Always define it.

### Critical Gotchas

- **`init-metadata` is mandatory after any structural change** (create-node, create-edge, delete, rename). Without it the frontend cannot render the new nodes — they show as black dots, connections are missing, and routing breaks silently.
- **`--libraries` is mandatory on `create-node`, `create-webhook`, and `create-code-agent-node`** for any non-stdlib import (requests, pandas, etc.). Without it the node's `libraries` field is empty and imports fail silently at runtime. Always include `--libraries` at creation time — do not use `patch-libraries` as a workaround.
- **Node IDs change on every UI save.** The frontend deletes and recreates nodes. Never hardcode DB IDs — always query first.
- **Non-CDT node ports must be `null`, not `[]`.** Frontend auto-generates ports only when `ports === null`.
- **CDT prompts must be a dict, not a list.** `converter_service.py` calls `.items()` — lists crash.
- **PATCH `python_code` without `libraries` wipes them.** Always include libraries in the payload.
- **Agent `tool_ids` PATCH is destructive replace.** Include all existing tool_ids.
- **Session messages filter uses `session_id=`** (not `session=`). Wrong param silently returns all rows.

---

## Flow Creation Checklist

When creating or planning a new flow, always follow this sequence and read `references/creating-flows.md` for full details:

1. `create-flow` — creates the graph
2. **Write code files first**, then create nodes with `--code-file` and `--libraries` in one command:
   `create-node "Process" --code-file process.py --libraries "requests,pandas"`
   Never create empty nodes and patch later — always pass `--code-file` + `--libraries` at creation time.
3. `create-edge` — wire nodes. **Trigger nodes (webhook, telegram) have no input port — nothing connects TO them.** When a flow has a trigger, both `__start__` and the trigger connect independently to the same downstream node:
   `create-edge "__start__" "Data Enricher"` (enables manual Run button)
   `create-edge "API Intake" "Data Enricher"` (webhook-triggered path)
   Without a `__start__` edge, `run-session` fails with "No node connected to start node".
4. **`init-metadata`** — run this after every structural change, no exceptions (without it: black dots, missing connections, broken routing)
5. Set `__start__` node variables — use DDD-style domain dicts (e.g. `{"jira": {"project_key": ..., "base_url": ...}}`)
6. `test-flow --verify` — validate structure + file/DB/metadata sync

For EpicChat flows, also read `references/epicchat.md` for input_map, output_schema, and build mode setup.

## When to Read Reference Files

This skill has detailed reference files for specific tasks. Read them when the situation calls for it — they're not needed for routine inspection or debugging.

| Task | Read this file |
|---|---|
| Need CLI command syntax or examples | `references/commands.md` |
| **Creating or planning** a new flow, nodes, edges, or wiring | `references/creating-flows.md` |
| Working with Code Agent nodes or EpicChat | `references/epicchat.md` |
| Debugging a failed session or API errors | `references/troubleshooting.md` |

---

## Session Debugging

When asked to check sessions, use the `sessions` command:

- **Recent sessions across all flows:** `sessions -n 5 -r` (no `-g` needed)
- **Sessions for a specific flow:** `sessions -g 55 -n 2 -r`
- **Don't know the flow ID?** Run `list -r` first to see all flows with their IDs
- **Inspect a specific session:** `session-inspect <session_id> -r`
- **Timing breakdown:** `session-timings <session_id> -r`

Flags can go in any order: `sessions -g 55 -n 2 -r` and `sessions -r -g 55 -n 2` both work.

---

## Lessons Learned

> When you discover new system behavior or encounter a recurring problem, add a note here.

- **Edges use integer node IDs, not name strings.** The DB stores `start_node_id` / `end_node_id` as integers. The CLI resolves node names to IDs automatically — you still pass names like `create-edge "__start__" "Data Enricher"`. The `edges` command shows both names and IDs. Renaming a node does NOT require edge updates (IDs are stable).
- **Graph.metadata is no longer used (post-RC).** The frontend saves `{nodes:[], connections:[]}` on every UI save. Node positions are stored in each node's own `metadata` JSON field. Connections are derived from DB edges at load time. The backend runtime reads directly from DB models. All `patch-*` commands write only to DB.
- **`init-metadata` sets node positions** by PATCHing each node's own `metadata` field with `{position, color, icon, size}`. It does NOT write to `Graph.metadata`.
- **Decision Table nodes have NO edges — only DB refs.** DT outputs are wired via `condition_group.next_node_id`, `default_next_node_id`, `next_error_node_id`. Use `connections` (not `edges`) to see DT wiring. When rewiring, use `patch-dt`.
- **Python node API endpoint is `/pythonnodes/`** (no hyphen). Other endpoints: `/code-agent-nodes/`, `/crewnodes/`, `/llmnodes/`.
- **DT `condition_groups` PATCH requires `conditions: []` in each group.** The viewset calls `pop("conditions")` — missing key causes silent rollback. The `patch-dt` command auto-adds this.
