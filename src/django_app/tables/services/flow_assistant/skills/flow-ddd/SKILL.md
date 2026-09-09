---
name: Domain-Driven-Flow-Design
description: Use when designing the variables namespace for an EpicStaff flow, translating business requirements into node graph contracts, or deciding which node type fits a responsibility.
---

# Domain-Driven Flow Design

A flow is a program whose only shared state is the `variables` dict. Every node reads through `input_map` and writes through `output_variable_path`. A well-designed flow treats `variables` as its domain model, shaped deliberately rather than accumulated node by node.

This skill is your reference for explaining or reviewing how a flow's `variables` namespace and node choices hold together. Companion: `flow-qa` — the structural/wiring checklist for a flow you're reviewing end to end.

---

## Core Principle — One Namespace, Shaped as Domains

There is exactly one shared store: `variables`. Every downstream `input_map` path resolves into it, every `output_variable_path` writes into it.

A good flow does not treat `variables` as a bag of flat keys. It shapes it as domain dicts — each top-level key is a bounded context. This keeps the namespace readable as the flow grows, and makes node responsibilities visible.

```json
// Bad — flat, every node scribbles in the same scope:
{
  "city": "Amsterdam",
  "temperature": 18.5,
  "service_account_info": {...},
  "model_id": "gpt-5",
  "jira_url": "..."
}

// Good — DDD-style, domains are explicit:
{
  "request":  { "city": "Amsterdam", "units": "celsius" },
  "weather":  { "temperature": null, "conditions": null },
  "gchat":    { "service_account_info": {...} },
  "model": { "model_id": "gpt-5", "provider_id": "openai" },
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

## What Good `variables` Design Looks Like — Four Rules

### 1. Every path should be declared — but a missing one doesn't crash, it goes quietly wrong
Every variable a node reads should exist in the start node's `variables` at session start, even if the value is initially `null`. But when a path IS missing, `map_variables_to_input` does not raise. It catches the lookup failure, logs a warning, and sets the value to `None` — or to the literal string `"not found"`, only when the caller passes `set_missing_variables=True` (used for `output_map` resolution). That makes a missing path worse than a crash in practice: no stack trace, just a `None` that surfaces several nodes downstream as a confusing bug.

When reviewing a flow, don't treat "it won't crash" as safety — trace every `input_map` path back to a start-node declaration or an upstream writer regardless.

Two real, intentional escape hatches exist for paths that may legitimately be absent:
- **Pipe-default syntax** — `"key": "variables.a.b|fallback"` in an `input_map` value supplies `fallback` when the path is missing. The fallback is coerced: `null`/`none` → `None`, `true`/`false` → bool, all-digits → `int`, anything else stays a string.
- **List-index paths** — `variables.items[0]` resolves through a list index, not just dict keys.

Both are the correct answer to "what if this path may not exist" — prefer them over letting a silent `None` propagate.

### 2. Group by bounded context, not by data shape
Top-level keys are domains — things the business talks about. Typical domains:
- `request` — the invoking user's input (what the webhook/trigger brought in, or the initial question).
- `config` (or per-system: `jira`, `gchat`, `slack`) — credentials and endpoints for external systems.
- Output domains named after what is produced (`weather`, `report`, `ticket`, `transcript`).
- `session` — optional; state that survives across turns of the same session.

A domain named after a node (e.g. `python_node_1`) is a smell — domains are nouns in the problem space, not implementation artifacts.

### 3. One writer per path
Two nodes writing the same `variables.<path>` makes execution order hidden logic. Each path should have exactly one writer. If two nodes enrich the same thing, they should write to different subpaths and merge in a single dedicated node:
- `fetch_weather` → `variables.weather.raw`
- `format_weather` → `variables.weather.report_text`
- downstream consumers read whichever they need.

### 4. Readers explicitly name what they need
`input_map` keys are local kwargs — they should name the parameter the function takes, not the domain path:
```json
{
  "city":         "variables.request.city",
  "weather_data": "variables.weather.raw"
}
```
This keeps a node self-documenting — reading its `main()` signature tells you exactly what it consumes.

---

## Python Node `main()` — The Implicit Input Map

When a `python` node has no explicit `input_map`, the runtime auto-generates one from `main()` parameter names: each param `foo` maps to `variables.foo`.

Consequences worth flagging when reviewing:
- Granular parameter names matter. `def main(city, units)` maps to `variables.city`, `variables.units` — flat, top-level.
- A parameter named `variables` creates `variables: "variables.variables"` — almost always a bug.
- To read a nested path, the node needs an explicit `input_map`. `def main(jira)` with `input_map = {"jira": "variables.jira"}` works fine.

A node whose parameter names don't line up with the domain structure, and has no explicit `input_map` to compensate, is reading the wrong thing at runtime — worth calling out.

---

## Choosing the Right Node for a Responsibility

The question when explaining a node's presence in a flow is always: "What is the right primitive for this responsibility?"

| Responsibility in the spec | Node |
|---|---|
| Fetch data from a known API, deterministic inputs/outputs | `python` |
| Validate a payload, shape an error response | `python` |
| Map a raw API response into domain objects | `python` |
| Pick one of a small fixed set of targets by a Python boolean rule | `decision_table` if 3+ branches; `conditional_edge` if 2 |
| Decide next step using LLM judgment over free text | `classification_decision_table` |
| Compose a narrative, summarize, hold a persona, or converse — as one wiring point in the graph | `task` (its own `agent_definition`, one node = one wiring point) |
| Same, but as an ordered sequence of sub-steps under one persona (e.g. draft → critique → revise) that only needs one entry/exit in the graph | `agent` (bundles an ordered list of internal sub-tasks; nothing else in the graph can wire between them) |
| Parse a user-uploaded document | `file_extractor` |
| Transcribe an audio message | `audio_transcription` |
| Start on an external event or schedule | `webhook_trigger` / `telegram_trigger` / `schedule_trigger` |
| Reuse a whole existing flow | `subgraph` |

Heuristics that matter:
- **If the logic is a pure function of structured inputs, `python` is right.** It is cheaper, faster, and more deterministic than any LLM-backed node.
- **`task` and `agent` are both LLM-backed graph nodes, each with its own `agent_definition` — they are alternatives, not a pair.** A `task` node is one LLM step with its own `instructions`, `output_schema`, and wiring point; use it when a single open-ended step (drafting a reply, summarizing free text, deciding between options that don't reduce to a boolean rule) needs to sit in the graph like any other node, with its own edges in and out. An `agent` node bundles an ordered list of internal sub-tasks (each with its own `instructions` and `output_schema`, able to reference earlier sub-tasks as context) under one `agent_definition` — use it when several LLM sub-steps genuinely belong together as one unit, and nothing else in the graph needs to intervene between them. The sub-tasks inside an `agent` node are not separate graph nodes and can't be individually wired.
- **`crew` is the older project/crew abstraction that predates `agent`/`task`.** It still runs in legacy flows and is deprecated — a flow being reviewed today should be using `agent`/`task`, not `crew`. Flag a `crew` node in an otherwise-new flow as worth migrating, not as broken.
- **`classification_decision_table` is the LLM-backed node for branching** — it applies an LLM's judgment as a routing rule over fuzzy text. `agent` nodes are also LLM-backed, but for generation, not branching; don't reach for an `agent` to pick between a fixed set of outcomes — that's what `classification_decision_table` is for.
- **Use `decision_table` when branching is a business rule expressible as Python boolean expressions over variables.** Use `conditional_edge` when branching is a short Python expression that returns a target node's name and there are just two paths.
- **Use `subgraph` when the sub-workflow is genuinely reusable and has its own lifecycle.** Copy-pasting nodes is worse than a subgraph, but a subgraph called only once is pure indirection.

---

## Contracts — The Shape of Data Between Nodes

A well-specified flow has a clear contract for each edge — useful to reconstruct when explaining how data moves through a flow:

| From node | Writes | Shape | Read by |
|---|---|---|---|
| `Weather Request` (webhook_trigger) | `variables.request.city: str` | non-empty string, else 400 | `Fetch Weather` |
| `Fetch Weather` (python) | `variables.weather.raw` | `{temperature: float, conditions: str, humidity: int, wind_speed: float}` | `Format Report` |
| `Format Report` (python) | `variables.weather.report_text: str` | multi-line string | `Friendly Reporter` |
| `Friendly Reporter` (task) | `variables.weather.narration: {message: str, ...}` | shaped by the node's `output_schema` | `__end_node__` |

If this table can't be filled in from what the tools return, the flow's contracts are ambiguous — flag it as an open question rather than guessing the shape.

---

## Patterns That Work

### Trigger + manual dual-entry
Triggers have no input port, so both `__start__` and the trigger fan into the first real node:
```
__start__        ──▶ Validate Request
Weather Request  ──▶ Validate Request
```
Without the `__start__` leg, manual "Run" fails: "No node connected to start node".

### Validate-then-proceed
Right after a trigger, a `python` node whose only job is to validate inputs and shape errors is the expected pattern. It returns `{"error": "...", "status": 400}` on bad input, routed by a `decision_table` that short-circuits to end on error, otherwise continues.

### Fan-in at end node
Multiple success/error paths converge on `__end_node__`, whose `output_map` picks the right fields. That's cheaper than funneling every path through one pre-end "merge" node.

### Enrichment pipeline
`request` → `fetch_raw` → `normalize` → `classify` → `respond`. Each node writes to its own subpath (`variables.raw`, `variables.normalized`, `variables.classification`). Downstream nodes read only what they need.

### Decision-table routing with manipulation
When a branch also needs to tweak `variables` before routing, the right place is the group's `manipulation` field on the decision-table node — not a follow-up `python` node. It keeps the routing atomic.

---

## Patterns That Break

- **Flat variable namespace.** `variables.city`, `variables.api_key`, `variables.temperature` — grows into a minefield. Domain dicts are the fix.
- **Two writers, one path.** Order-dependent correctness. Always resolvable by splitting into subpaths.
- **Undeclared variables.** Every `input_map` path should exist at session start — even though a missing one won't crash (see Rule 1), it will misbehave silently.
- **`agent`/`task` where `python` would do.** If the work is deterministic and typed, an LLM adds latency, cost, and non-determinism for no benefit.
- **`python` node as a hidden router.** If branching is the node's real job, it belongs in a `decision_table` or `conditional_edge` instead — visible in the graph rather than buried in code.
- **Decision-table node with overlapping groups.** First match wins, in declared order. Ambiguous rules silently route to the first listed group. Order groups deliberately or write mutually exclusive conditions.
- **Webhook handler that returns nothing.** The returned dict merges into `variables`. A handler that does `return None` or omits `return` writes nothing — downstream reads will fail.
- **Changing domain shape mid-flow.** Node A writing `variables.user = "alice"` then node B overwriting `variables.user = {"name": "alice"}` is a bug waiting to happen. One shape per path, picked up front.

---

## Persistent Variables — Cross-Session State

By default, every session starts fresh from the start node's `variables`. A flow can carry state forward across sessions by declaring **persistent variables** — but only one scope of the feature is actually implemented. Know the gap before explaining it to anyone.

### How it works, and what's actually wired up

1. `Graph.enable_persistent_variables` is read-only and derived — there is no manual toggle. It flips `true` the moment the start node declares at least one `organization` path, and back to `false` when the last one is removed.
2. The start node's `variables` declares two lists under a `persistent_variables` key:
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
3. **Only the `organization` list does anything at runtime.** Session start merges only `GraphOrganization.persistent_variables` in; session end writes back only the `organization` paths. Both are gated on `Graph.enable_persistent_variables`.
4. **The `user` list is inert.** The per-user storage row is only ever `get_or_create`d so the session has a valid FK to point at — nothing is ever read from it or written to it. Declaring a path under `user` saves fine and does nothing at runtime: no per-user state persists.
5. Because the flag derives from `organization` paths only, a start node that declares paths ONLY under `user` leaves `enable_persistent_variables` false — meaning nothing persists at all, not even in the sense of the inert `user` paths looking active.

### Validation is loud, not silent
Every declared path — in both `organization` and `user` lists — must already exist under `variables` in the same payload, or the save is rejected outright at validation time with a `ValidationError` naming the missing path. There is no silent-drop behavior for an undeclared persistent path; the platform refuses the save up front.

### What's genuinely unchecked
- **No duplicate-across-scopes check.** A path can legally appear in both `organization` and `user` — nothing stops it (moot in practice today, since `user` doesn't persist anyway).
- **No array-index check.** Declared paths must navigate object properties only (`context.history`, not `context.items.0` or `context.items[0]`) — pointing one at a list index isn't rejected, it just misbehaves silently at merge time.

### Worth checking when reviewing
- Persistent paths are usually nested under a domain dict (e.g. `variables.context`) — convention only, not enforced; a flat `variables.counter` works identically. Nesting is there to avoid the flat-namespace problems above, not because the platform requires it.
- The declared path must be the *exact* path the node writes to. If a node's `output_variable_path` is `variables.context.counter` but the declared persistent path is `counter` (i.e. `variables.counter`), the session runs fine and updates the mismatched path in-session — but the declared path never changes, so nothing gets written back, and no error surfaces anywhere. Worth double-checking whenever a node has been copied between flows with a different variable layout.

### When it's the right call
- Flow-wide (organization-scoped) shared state today: shared context, org-level counters, config that should stick across every user's runs.
- Not yet for per-user memory — the `user` list exists in the schema but does nothing. If someone wants per-user isolation across sessions, say so plainly rather than pointing them at the `user` list as if it worked.
- Not for secrets that should always be pulled fresh from a vault — persistent values sit in the DB and can go stale.

---

## Review Checklist

When explaining or reviewing a flow's variable design, you should be able to answer:

1. What are the domains in `variables`? Name each with a business noun.
2. For every domain, what paths exist at session start? (They should all be in the start node, even as `null`.)
3. For every node, what does it read? What does it write? Is the type/shape clear?
4. Is each path written by exactly one node?
5. Where are the branches — `decision_table` or `conditional_edge`? What are the groups and their targets?
6. Where are the end points? What does `output_map` pick from `variables`?
7. Is there a trigger? If so, is `__start__` also connected to the first real node (dual entry)?
8. For each `task` node: what tools does it need, and what's its `output_schema`? For each `agent` node: what tools/surfaces does it need, and what's each internal sub-task's `output_schema`?
9. Does the flow need cross-session state? If so, which paths are declared under `organization` (the only scope that actually persists), and are they nested under a domain dict like `variables.context`?

When every question has a concrete, tool-grounded answer, the design holds together. Anything you can't answer from the tools is an open question — say so rather than guessing.
