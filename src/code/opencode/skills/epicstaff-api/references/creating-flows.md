# Creating Flows

Read this when building a new flow from scratch. Every new flow must satisfy all of the following before it's considered complete.

All commands use: `python3 epicstaff_tools.py [-r] [-g <GRAPH_ID>] <command> [args]`

## Creating Resources

**Workflow: write code files FIRST, then create nodes with `--code-file` + `--libraries` in one command.**
Never create empty nodes and patch later — always pass both flags at creation time.

```
# Create a new flow
create-flow "My New Flow" --description "Description"

# Python node — write the code file first, then:
-g <ID> create-node <name> --code-file code.py --libraries "requests,httpx"

# Code Agent node (OpenCode-powered)
-g <ID> create-code-agent-node <name> \
  --llm-config 2 --agent-mode build --system-prompt "You are helpful" \
  --code-file stream_handler.py --libraries "requests,httpx" \
  --output-variable-path code_reply --x 400 --y 100

# Webhook Trigger node
-g <ID> create-webhook <name> \
  --code-file webhook_handler.py --webhook-path "my_webhook" --x -400 --y 0

# Edges — trigger nodes (webhook, telegram) have NO input port.
# Nothing connects TO a trigger. Both __start__ and the trigger
# connect to the same downstream node independently:
-g <ID> create-edge "__start__" "My Node"
-g <ID> create-edge "My Webhook" "My Node"
-g <ID> create-edge "My Node" "Next Node"
# Without __start__ edge, run-session fails: "No node connected to start node"

# Generate metadata from DB state (REQUIRED after creating nodes/edges)
-g <ID> init-metadata

# Create a tool
create-tool <name> --description <desc> --code-file tool.py

# Create crew, agent, task
create-crew <name> --process sequential
create-agent <role> --goal <goal> --llm-config <CFG_ID> --crew-id <CREW_ID>
create-task <name> --instructions <instructions> --agent-id <AGENT_ID> --crew-id <CREW_ID>
```

Every agent needs `--llm-config` set at creation or PATCHed afterwards. To find available config IDs: `-r agents` (check the `llm_config` field on existing agents).

When adding a crew to a flow as a crew node, set `input_map` (maps parameters to flow variables) and `output_variable_path` (e.g. `"variables"` or `"variables.<domain>"`).

## Start Node Variables — Declare Everything

The `__start__` node's `variables` dict is the initial state. Every variable that any node reads via `input_map` must be declared here, even if initially `null`. Missing variables silently resolve to `None` at runtime.

## DDD-Style Dict Variables

Group related variables into domain dicts rather than using a flat namespace. This keeps the variable space clean and lets nodes access data via dot notation.

```json
// Bad — flat namespace:
{ "service_account_info": {...}, "opencode_model_id": "gpt-5" }

// Good — DDD-style:
{
  "gchat": { "service_account_info": {...} },
  "opencode": { "model_id": "gpt-5", "provider_id": "openai" }
}
```

Then `input_map` references: `"service_account_info": "variables.gchat.service_account_info"`.

## Python Node `main()` Signature Rules

The runtime auto-generates `input_map` from `main()` parameter names: each param `foo` maps to `variables.foo`. This means parameter names are the input map keys.

Use individual, granular parameters — not a broad `variables` dict. Each parameter should map to the smallest piece of state the node actually needs. A parameter named `variables` creates a circular mapping (`variables = variables.variables`) which is almost never what you want.

```python
# Bad — causes variables = variables.variables:
def main(variables: dict) -> dict:
    config = variables["jira"]

# Good — auto-maps to jira = variables.jira:
def main(jira: dict) -> dict:
    base_url = jira["base_url"]
```

## Node Libraries

Every `create-node`, `create-webhook`, and `create-code-agent-node` must include `--libraries` at creation time if the code imports non-stdlib packages. `init-metadata` does not detect or carry over libraries — they come solely from the DB. Do not use `patch-libraries` as a workaround — always specify `--libraries` on the create command.

## Node Placement

Every new node needs coordinates (`--x` and `--y`). Check existing positions first (`nodes` command).

- X increases left-to-right (each step ~400–500px apart)
- Y increases top-to-bottom (stacked nodes at same X, ~60px apart)
- New steps start at the main Y baseline (~100–200)
- Backward-connection nodes go up to match the Y of their target
- Never move existing nodes without user permission

## Canvas Notes

Metadata-only annotations. Use sparingly — only when a node's purpose is non-obvious.

```
-g <ID> create-note "Handles queueing" --near "Stream Coding GChat"
-g <ID> create-note "Important" --x 400 --y 200 --color "#ffd1d1"
```

## `init-metadata` Limitations

`init-metadata` rebuilds metadata from DB state. It handles node positions, connections, `input_map`, `output_variable_path`, and project node `data.id`.

It does **not** handle: start node variables, DDD-style nested paths (generates flat `variables.X`), or libraries on webhook/code-agent nodes.

After running it, always review and patch: start node variables, Code Agent input_maps, and DDD path adjustments.

## End-to-End Recipe

```
# 1. Create flow
create-flow "My Flow" --description "..."

# 2. Create nodes (always include --libraries)
-g <ID> create-node "Process" --code-file process.py --libraries "requests"
-g <ID> create-code-agent-node "Agent" --llm-config 2 \
  --code-file handler.py --libraries "google-auth"

# 3. Wire edges + generate metadata
-g <ID> create-edge "__start__" "Process"
-g <ID> create-edge "Process" "Agent"
-g <ID> init-metadata

# 4. Set start node variables (DDD-style) via Domain dialog or API
# 5. For EpicChat: see references/epicchat.md
# 6. Verify + test
-r -g <ID> test-flow --verify
```
