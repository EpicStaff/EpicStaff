---
name: Domain-Driven-Flow-Design
description: Use when designing the variables namespace for an EpicStaff flow, translating business requirements into node graph contracts, or deciding which node type fits a responsibility.
---

# Domain-Driven Flow Design

A flow is a program whose only shared state is the `variables` dict. Every node reads through `input_map` and writes through `output_variable_path`. Treat `variables` as the domain model — design it before you place the nodes.

This skill complements:
- `flow-interview` / `flow-architecture` — producing the spec and the abstract graph.
- `flow-node-types` — what each node type can actually do.
- `flow-build` — the mechanics of creating the nodes via MCP tools.

---

## Core Principle — One Namespace, Shaped as Domains

There is exactly one shared store: `variables`. Every downstream `input_map` path resolves into it, every `output_variable_path` writes into it.

Do not treat `variables` as a bag of flat keys. Shape it as domain dicts — each top-level key is a bounded context. This keeps the namespace readable as the flow grows, and makes node responsibilities visible.

```json
// Bad — flat, every node scribbles in the same scope:
{
  "city": "Amsterdam",
  "temperature": 18.5,
  "service_account_info": {...},
  "opencode_model_id": "gpt-5",
  "jira_url": "..."
}

// Good — DDD-style, domains are explicit:
{
  "request":  { "city": "Amsterdam", "units": "celsius" },
  "weather":  { "temperature": null, "conditions": null },
  "gchat":    { "service_account_info": {...} },
  "opencode": { "model_id": "gpt-5", "provider_id": "openai" },
  "jira":     { "base_url": "...", "project_key": "..." }
}
```

Input map then reads as intent:
```json
{
  "city":     "variables.request.city",
  "jira_cfg": "variables.jira"
}
```

---

## Designing `variables` — Four Rules

### 1. Declare every path before runtime
Every variable any node reads must exist in the start node's `variables` at session start, even if the value is initially `null`. Missing paths raise `AttributeError` inside `map_variables_to_input`. Only the end node's `output_map` silently falls back to `"not found"`.

Concretely: before building a flow, list every `variables.<path>` that any node will reference, and seed all of them in the start node.

### 2. Group by bounded context, not by data shape
Top-level keys are domains — things the business talks about. Typical domains:
- `request` — the invoking user's input (what the webhook/trigger brought in, or the initial question).
- `config` (or per-system: `jira`, `gchat`, `slack`) — credentials and endpoints for external systems.
- Output domains named after what is produced (`weather`, `report`, `ticket`, `transcript`).
- `session` — optional; state that survives across turns of the same session.

Avoid domains named after a node (e.g. `python_node_1`). Domains are nouns in the problem space, not implementation artifacts.

### 3. One writer per path
Two nodes writing the same `variables.<path>` makes execution order hidden logic. Give each path exactly one writer. If two nodes enrich the same thing, write to different subpaths, then merge in a single dedicated node:
- `fetch_weather` → `variables.weather.raw`
- `format_weather` → `variables.weather.report_text`
- downstream consumers read whichever they need.

### 4. Readers explicitly name what they need
`input_map` keys are local kwargs — name them for the parameter the function takes, not for the domain path:
```json
{
  "city":         "variables.request.city",
  "weather_data": "variables.weather.raw"
}
```
This keeps nodes self-documenting — you can read a node's `main()` signature and know exactly what it consumes.

---

## Python Node main() — The Implicit Input Map

When a `python` node is created without an explicit `input_map`, the runtime auto-generates it from `main()` parameter names: each param `foo` maps to `variables.foo`.

Consequences:
- Pick granular parameter names. `def main(city, units)` maps to `variables.city`, `variables.units`.
- A parameter named `variables` creates `variables: "variables.variables"` — almost always a bug.
- To read a nested path, set `input_map` explicitly. `def main(jira)` with `input_map = {"jira": "variables.jira"}` works fine.

Align parameter names with domain structure so the auto-mapping does the right thing, or set `input_map` explicitly when you need a nested path.

---

## Choosing the Right Node for a Responsibility

Business requirements translate to nodes, not the other way around. The question is always: "What is the right primitive for this responsibility?"

| Responsibility in the spec | Node |
|---|---|
| Fetch data from a known API, deterministic inputs/outputs | `python` |
| Validate a payload, shape an error response | `python` |
| Map a raw API response into domain objects | `python` |
| Pick one of a small fixed set of targets by rule | `table` (CDT) if 3+ branches; `edge` if 2 |
| Decide next step using LLM reasoning over free text | `code-agent` |
| Compose a final narrative from structured data | `code-agent` |
| Multi-step agent work with multiple roles and task handoff | `project` (crew node) |
| Assistant-style interaction with the user (EpicChat) | `code-agent` |
| Parse a user-uploaded document | `file-extractor` |
| Transcribe an audio message | `audio-to-text-node` |
| Start on external event | `webhook-trigger` / `telegram-trigger` |
| Reuse a whole existing flow | `subgraph` |

Heuristics that matter:
- **If the logic is a pure function of structured inputs, use `python`.** It is cheaper, faster, more reliable than any agent node.
- **If the logic needs reasoning over fuzzy text, use `code-agent`.**
- **Reach for `project` (crew) only when multiple roles collaborate.** A single-agent crew is almost always worse than a plain `code-agent` node.
- **Use CDT when branching is a business rule expressed as predicates over variables.** Use conditional `edge` when branching is a short Python expression that returns a node name.
- **Use `subgraph` when the sub-workflow is genuinely reusable and has its own lifecycle.** Copy-pasting nodes is worse than a subgraph, but a subgraph you only call once is pure indirection.

---

## Contracts — The Shape of Data Between Nodes

Before building, write out the contract for each edge:

| From node | Writes | Shape | Read by |
|---|---|---|---|
| `Weather Request` (webhook) | `variables.request.city: str` | non-empty string, else 400 | `Fetch Weather` |
| `Fetch Weather` | `variables.weather.raw` | `{temperature: float, conditions: str, humidity: int, wind_speed: float}` | `Format Report` |
| `Format Report` | `variables.weather.report_text: str` | multi-line string | `Friendly Reporter` |
| `Friendly Reporter` (code-agent) | `variables.weather.narration: {message: str, ...}` | `output_schema` required | `__end_node__` |

If you can't fill this table from the spec, the spec is ambiguous — flag it as an open question, don't guess.

---

## Patterns That Work

### Trigger + manual dual-entry
Triggers have no input port, so both `__start__` and the trigger need to fan into the first real node:
```
__start__        ──▶ Validate Request
Weather Request  ──▶ Validate Request
```
Without the `__start__` leg, manual "Run" fails: "No node connected to start node".

### Validate-then-proceed
Right after the trigger, put a `python` node whose only job is to validate inputs and shape errors. Return `{"error": "...", "status": 400}` on bad input; route to CDT that short-circuits to end on error, otherwise continues.

### Fan-in at end node
Multiple success/error paths converge on `__end_node__`, whose `output_map` picks the right fields. This is cheaper than trying to funnel paths through one pre-end "merge" node.

### Enrichment pipeline
`request` → `fetch_raw` → `normalize` → `classify` → `respond`. Each node writes to its own subpath (`variables.raw`, `variables.normalized`, `variables.classification`). Downstream nodes read only what they need.

### Decision-Table routing with manipulation
When a branch also needs to tweak `variables` before routing, put the tweak in the group's `manipulation` — not in a follow-up `python` node. Keeps the routing atomic.

---

## Patterns That Break

- **Flat variable namespace.** `variables.city`, `variables.api_key`, `variables.temperature` — grows into a minefield. Use domain dicts.
- **Two writers, one path.** Order-dependent correctness. Always resolvable by splitting into subpaths.
- **Undeclared variables.** Every `input_map` path must exist at session start.
- **Agent where Python would do.** If the work is deterministic and typed, an LLM adds latency, cost, and non-determinism.
- **Python node as a hidden router.** If branching is the node's real job, extract to a CDT or conditional `edge` — it becomes visible in the graph.
- **CDT with overlapping groups.** First match wins, in declared order. Ambiguous rules silently route to the first listed group. Order groups specifically or write mutually exclusive conditions.
- **Webhook handler that returns nothing.** The returned dict merges into `variables`. A handler that does `return None` or omits `return` wipes nothing but writes nothing — downstream reads will fail.
- **Changing domain shape mid-flow.** Don't have node A write `variables.user = "alice"` then node B overwrite `variables.user = {"name": "alice"}`. Pick one shape up front.

---

## Persistent Variables — Cross-Session State

By default, every session starts fresh from the start node's `variables`. When a flow needs to carry state forward across sessions (e.g., conversation history, user preferences, accumulated context), enable **persistent variables**.

### How it works

1. `Graph.persistent_variables = true` — opt-in flag on the flow (set when creating or patching the flow).
2. The start node's `variables` declares two lists under a special `persistent_variables` key:
   ```json
   {
     "variables": {
       "context": { "history": [], "user_prefs": {} }
     },
     "persistent_variables": {
       "organization": ["context.user_prefs"],
       "user": ["context.history"]
     }
   }
   ```
3. On each new session, the platform loads the last successfully completed session's values at those paths and merges them into `variables` before the flow starts.

### Two scopes

| Scope | Stored in | Shared across |
|---|---|---|
| `organization` | `GraphOrganization.persistent_variables` | All users of the same flow deployment |
| `user` | `GraphOrganizationUser.persistent_variables` | Only the specific user running the session |

Use `organization` for shared config (API keys overridden at runtime, shared context). Use `user` for per-user state (conversation history, preferences, counters).

### Design rules for persistent paths

- **All persistent paths must live under `variables.context`** — the platform validates this. Paths outside `context` are rejected.
- **No duplicates across scopes** — a path cannot appear in both `organization` and `user`.
- **No array indices** — paths must navigate object properties only (e.g., `context.history` not `context.items.0`).
- **Declare the path in `variables.context` at session start, even as `null` or `[]`** — the persistent merge overwrites, not creates. A missing key is not created by the merge.
- **One writer per path, still applies** — the same node that writes a persistent path in the current session becomes the source for the next session's merge.

### When to use

- EpicChat assistant flows where the agent needs to recall prior turns across sessions.
- Flows that accumulate results over time (e.g., a nightly report that appends to a running log).
- Flows where a user can override a setting that should stick for future runs.

### When NOT to use

- Within a single session — use `variables` normally. Persistence only crosses session boundaries.
- For secrets or credentials that should always be pulled fresh from a vault — persistent values are stored in the DB and could become stale.

---

## Pre-Build Checklist

Before creating any nodes, you should be able to answer:

1. What are the domains in `variables`? Name each one with a business noun.
2. For every domain, what paths will exist at session start? (They all go in the start node, even as `null`.)
3. For every node, what does it read? What does it write? Can you name the type / shape?
4. Is each path written by exactly one node?
5. Where are the branches? CDT or conditional `edge`? List the groups and their targets.
6. Where are the end points? What does `output_map` pick from `variables`?
7. Is there a trigger? If yes, is `__start__` also connected to the first real node?
8. For each agent-style node: what tools does it need? What's its `output_schema`?
9. Does the flow need cross-session state? If yes: which paths persist, at which scope (`organization` or `user`)? Are they all under `variables.context`?

When every question has a concrete answer grounded in the spec, you're ready to build.
