---
name: Flow-QA-Checklist
description: Use when an EpicStaff flow build is complete and needs pre-submit validation before being considered done.
---

# Flow QA Checklist

Static validation of a built flow. Treat a flow as a program — reachable, well-typed, and side-effect-aware. This skill produces a pass/fail report with actionable findings.

All checks use the Flow Assistant's own read tools: `get_flow_overview`, `get_node`, `get_edges_from`, `get_edges_to`, `list_node_types`. Do not reference MCP tools or external CLI tools — they are not available in this context.

Companion: `flow-ddd` skill if you need to explain variable-namespace findings.

---

## When to Use

**Use this skill when:**
- A flow has just been built and needs pre-submit validation.
- Before declaring a flow "ready" for the user.
- After any structural change (add/delete node or edge), before handing back.
- The user asks "is it ready?", "lint this flow", "review the flow", "QA it".

**Do NOT use when:**
- The flow is mid-build — run QA once at the end, not after every partial change.
- The flow is actively broken with a known, specific bug the user has already described — go straight at that bug instead of running the full checklist, then QA once it's fixed.

---

## QA Output — Pass/Fail Report

Produce a report with these sections:

```
## QA Report — <Flow Name> (#<flow_id>)

### Result
PASS | FAIL

### Structural
[✓|✗] __start__ connects to downstream
[✓|✗] No dangling nodes (every non-end node has outgoing route)
[✓|✗] Trigger nodes have no input edges
[✓|✗] Every edge endpoint resolves to a live node in this graph
[✓|✗] decision_table / classification_decision_table route targets resolve to real nodes

### Data Flow
[✓|✗] Every `input_map` path is declared in start variables or written upstream
[✓|✗] Every declared start variable is actually read by something (or marked intentionally seeded)
[✓|✗] No two nodes write to the same `output_variable_path`
[✓|✗] End node `output_map` references paths that get written

### Per-Node Correctness
[✓|✗] python / webhook_trigger nodes have non-empty `libraries` if code imports non-stdlib
[✓|✗] python / webhook_trigger nodes define `def main(...)`
[✓|✗] decision_table rules read as valid Python boolean expressions (spot-check)
[✓|✗] classification_decision_table rules have sane `field_expressions` / routing (spot-check)

### Findings
1. <finding 1 — severity, location, suggested fix>
2. ...

### Recommended next step
<build is clean | fix specific patch | needs clarification from user>
```

Severity:
- **blocker** — flow will fail at runtime. Must fix.
- **warning** — not a guaranteed failure but likely a bug. Investigate.
- **nit** — code smell, naming, unused variable. Fix at leisure.

---

## The Checks — What and How

Run each check explicitly. Do not skip the ones that "look obviously fine" — the point is evidence, not intuition.

### 1. Structural reachability

Tools: `get_flow_overview`, `get_edges_from`, `get_edges_to`, `get_node`.

- `__start__` has at least one outgoing edge (verify with `get_edges_from`).
- Every non-trigger, non-end node is reachable from `__start__`. A node referenced by `decision_table` / `classification_decision_table` routing counts as reachable too.
- `conditional_edge` routing is invisible to `get_edges_from` / `get_edges_to` — `ConditionalEdge` rows live in a separate table from `Edge` and are not returned by either tool. A node with zero outgoing `Edge` rows may still be routed to from a `conditional_edge` node whose `source_node_id` points at it. Before flagging such a node as a dead end, check whether any `conditional_edge` node has that node as its source, then read that conditional_edge's `python_code_summary.code` to recover the string targets it can return. If you can't resolve the targets this way, report the reachability check as unverifiable for that node rather than as a blocker — don't invent a pass result, and don't invent a fail result either.
- Every execution path reaches the end node (or a decision-table error branch that reaches end).
- Trigger nodes (`webhook_trigger`, `telegram_trigger`, `schedule_trigger`) have zero incoming edges (verify with `get_edges_to`).
- When a trigger exists, `__start__` is also wired into the first real node (dual entry).
- Every edge's source and target id resolves to a node that actually exists in this graph — `get_edges_from`/`get_edges_to` returning an id that `get_flow_overview`/`get_node` can't find is stale wiring left over from a deleted node.
- `decision_table` routes: every rule's `routes_to_node_id`, plus the node-level `default_next_node_id` and `next_error_node_id`, resolve to a real node (verify by reading the node config via `get_node`).
- `classification_decision_table` routes: every rule's `routes_to_node_id`, plus the node-level `default_next_node_id` and `next_error_node_id`, resolve to a real node.

If any of these fail, the fix is almost always a missing edge or stale node config.

### 2. Data-flow continuity

Tools: `get_flow_overview` (node inventory), `get_node` (read each node's `input_map`, `output_variable_path`, and decision-table rule detail).

Build two tables:

**Writers table.** For every `output_variable_path` across all nodes: which node writes it.
- A path with two writers is a blocker unless the design is explicitly override-last-wins (document the intent).
- A path with zero writers is a blocker if anyone reads it.

**Readers table.** For every `input_map` value across all nodes: which node reads it.
- Every path must appear either (a) in the start node's initial `variables` or (b) in the writers table with an execution order that precedes the reader.
- A path read but never written is a blocker — even though the runtime won't crash on it (a missing path resolves quietly to `None`, or to a `|default` fallback if the `input_map` value uses pipe-default syntax), it's still a real bug worth flagging.

For end node `output_map`: every value path must appear in the writers table or start variables. If a value is referenced only via `output_map`, the runtime silently resolves it to the string `"not found"` — warning-level, not blocker.

### 3. Per-node correctness

For each node type, verify the per-type invariants.

- **start**: `variables` is a non-empty dict; every path any downstream `input_map` references is declared (even as `null`).
- **end**: `output_map` non-empty; every referenced path is written upstream (or acknowledged as default `"not found"`).
- **python**: code contains `def main(...)`; every import satisfies one of (a) stdlib, (b) appears in `libraries`; `input_map` keys map to kwargs of `main` or are explicit paths; `output_variable_path` set if output is used downstream.
- **webhook_trigger**: `python_code_summary.code` contains `def main(trigger_payload=None)`; `libraries` present; bad-input branches return `{"error": ..., "status": 400}`.
- **telegram_trigger** / **schedule_trigger**: has zero incoming edges (see check 1); downstream node consumes whatever payload shape the trigger produces.
- **task**: has an `agent_definition` set (a `task` node with no agent will fail at runtime); `instructions` non-empty; `output_schema`, if set, is valid JSON schema; `output_variable_path` set if the result is consumed downstream.
- **agent**: has an `agent_definition` set; its internal sub-tasks each have a unique `name`, a contiguous `order`, and any `context_task_ids` reference an earlier sub-task by `id` (forward references are invalid); `output_variable_path` set if the result is consumed downstream.
- **conditional_edge**: `python_code_summary.code` returns a string (assert in code), and that string is always a live node's name.
- **decision_table**: node-level `default_next_node_id` and `next_error_node_id` are both set (unset is a blocker — an unrouted default/error case falls back to END silently); every rule has a unique `rule_name`; `rule_type` is `simple` or `complex`; `simple` rules have non-empty `conditions[]` whose `expression` reads as a Python boolean expression; `complex` rules have a non-null top-level `expression` joining the conditions; every rule's `routes_to_node_id` resolves to a real node (null is only valid if the rule is deliberately left unwired — flag it if so).
- **classification_decision_table**: node-level `default_next_node_id` and `next_error_node_id` are both set; each rule's `route_code` (if used) is unique within the node; `field_expressions` meaningfully describes what the LLM should extract or classify; `continue_to_next_rule` correctly reflects whether a rule is meant to fall through to the next one; `prompt_id`, if set, references a real prompt; `routes_to_node_id` resolves to a real node.
- **subgraph**: referenced subgraph exists; circular references absent.
- **file_extractor**, **audio_transcription**: input is a path or file ref the runtime can consume; `output_variable_path` set.
- **crew** (deprecated/legacy): treat as a migration candidate rather than an error — flag it as a warning/nit suggesting a move to `agent`/`task`, not a blocker.

### 4. Error handling coverage

- Every trigger node has a validation step shortly after it (webhook typically → python validator that returns `{"error", "status": 400}` on bad input, routed to end via `decision_table`).
- Every `decision_table` / `classification_decision_table` has `next_error_node_id` set (blocker if unset — the runtime falls back to END silently).
- Every path that can raise (external HTTP calls, file parsing, LLM calls) either has an explicit try/except in the node code or sits upstream of a decision-table node that can route errors.

### 5. Side-effect placement

Side effects (external API writes, file writes, emails, messages) belong in clearly named nodes, not buried inside a `conditional_edge` or a decision-table `manipulation`. A reader of the graph should be able to see where side effects happen just from node names and types.

Flag as a **warning** any:
- Decision-table `manipulation` that calls `requests` / sends messages / writes files.
- `conditional_edge` code with side effects (it should only compute a target string).
- `python` node that both transforms data AND sends outbound messages — split responsibilities.

### 6. Naming and domain hygiene

Tie back to `flow-ddd`:
- `variables` is shaped as domain dicts, not a flat key bag.
- Node names describe responsibilities in business language ("Fetch Weather", not "Node 1").
- Decision-table rule names are short and distinctive — renaming them later can break canvas wiring that references them by name.

### 7. Runtime smoke test

Skip runtime smoke — Flow Assistant cannot run sessions. Report all findings as static only and note this limitation in the report.

---

## Working the Checklist — Execution Order

Do the checks in order. Stop and write up findings if a blocker surfaces early; a downstream check may depend on an earlier check being clean.

1. `get_flow_overview` — node inventory (types, ids, names) and edge count.
2. For each node: `get_node(node_id)` — full config, code, libraries, maps, decision-table rules.
3. `get_edges_from` / `get_edges_to` — wiring per node; build the full edge list.
4. Cross-reference: build the writers / readers tables from the node inventory.
5. Per-node correctness pass (uses decision-table detail from step 2).
6. Error handling and side-effect review.
7. Runtime smoke: not available — report findings as static only.

Do NOT patch in the middle of QA. Collect findings, then report them.

---

## Sample Finding — Good Format

```
Finding 2 — blocker
Node: Fetch Weather (python)
Issue: input_map has "city": "variables.request.city", but start variables declare
       "variables.request.message" instead. No upstream writer for variables.request.city.
Evidence: get_node(start_id) -> start.variables = {"request": {"message": null, "units": "celsius"}}
Fix: Either rename start var to `city`, or update the webhook validator to write
     `variables.request.city`, or update Fetch Weather's input_map to read .message.
```

A bad finding:
> The flow looks a bit off around the webhook.

Be specific. Every finding must cite the node, the symptom, the evidence from the tool output, and a concrete fix.

---

## Output Format

Format the report as the `message` field (Markdown). Include:
- An `openFlow` button.
- An `openNode` button for the first blocker finding (if any), targeting that node.
- Prompt chips: "Show me the details of finding 1", "Walk me through the data-flow issues".

Example:
```json
{
  "message": "## QA Report — Weather Report Demo (#55)\n\n**Result:** FAIL (1 blocker, 2 warnings)\n...",
  "action_message": [
    {"type": "button", "text": "Open flow", "action": "openFlow", "params": {"flowId": "55"}},
    {"type": "button", "text": "Open Fetch Weather", "action": "openNode", "params": {"flowId": "55", "nodeId": "<uuid>"}},
    {"type": "prompt", "text": "Show me the details of finding 1"},
    {"type": "prompt", "text": "Walk me through the data-flow issues"}
  ]
}
```

---

## Pass Criteria

A flow **passes** QA only when:
- Every blocker check is green.
- No unresolved `output_map` path that would silently resolve to `"not found"`.
- No stale edge endpoints (every edge resolves to live nodes on both ends).

Anything less is a **FAIL** — report the blockers first, warnings next, nits last.

---

## Do Not

- Do not patch during QA. Report findings and let the user apply fixes.
- Do not skip checks that "obviously pass" — the point is evidence.
- Do not invent a pass result. If you couldn't run a check, say so in the report.
- Do not reference MCP tools or external CLI commands — they do not exist in this context.
