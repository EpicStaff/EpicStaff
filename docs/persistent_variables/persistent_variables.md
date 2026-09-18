# Persistent Variables

**Source:** `tables/services/persistent_variables_service.py`

## Problem

By default every session starts fresh from the start node's declared `variables` and nothing survives past `END`/`ERROR`. Some flows need a value to carry forward across separate session runs — a running counter, conversation history, a user preference — without standing up external storage.

## Solution

A flow declares which dot-paths in its `variables` should persist. The platform remembers their values per-flow in the database, merges them back into `variables` at the start of every new session, and writes back whatever those paths hold when the session ends.

Only **organization-level** persistence is implemented. A `user`-level scope exists in the data model and in the declaration shape below, but there is no merge, seed, or write-back for it yet.

## Declaring a persistent variable

The start node's `variables` field carries the declaration alongside the actual values:

```json
{
  "variables": {
    "counter": 100
  },
  "persistent_variables": {
    "organization": ["counter"],
    "user": []
  }
}
```

- Any dot-path that resolves to an existing value under `variables` can be declared — depth is not restricted. `"counter"` and `"context.counter"` both work identically; there is no requirement to nest under a `context` key or any other domain dict.
- **Convention, not requirement:** grouping persistent variables under a domain dict (e.g. `context`) is recommended once a flow has more than a couple of them, purely to avoid flat-namespace collisions. Nothing in the code enforces this — `validate_start_node_variables` only checks that the declared path resolves to an existing value (including an explicit `null`).
- Declaring a path is the entire opt-in mechanism. There is no separate flag to flip: `Graph.enable_persistent_variables` is derived automatically — `true` the moment the start node declares at least one `organization` path, `false` again when the last one is removed. It's read-only on the `Graph` API; a client can't set it directly.

## The wiring must match the declared path

Declaring `"counter"` as persistent only has an effect if the node(s) that read and write that variable actually target `variables.counter` — via `input_map` for reads, `output_variable_path` for writes. If a node's `output_variable_path` points somewhere else (e.g. `variables.context.counter`, left over from copying the node from a different flow) while the start node declares `counter` as the persistent path, the node's output lands at the other path. The session runs and completes normally; the declared path is simply never touched, so there is nothing to write back — no error surfaces anywhere in the chain.

Whenever you copy a node between flows with a different variable layout, double-check `input_map` / `output_variable_path` still point at the path that's actually declared persistent.

## Lifecycle

1. **Declaration** — edit the start node's `persistent_variables` block (adding a path to `organization`, or removing one).
2. **Seed on save** — `sync_from_start_node()` runs on every start-node create/update: a newly declared path is seeded into storage from its default in `variables`; an already-declared path keeps its remembered value (a default-value edit doesn't clobber what's stored); a path no longer declared is dropped from storage.
3. **Run-time merge** — `build_run_variables()` (called from `run_session`, gated on `enable_persistent_variables`) deep-merges `GraphOrganization.persistent_variables` (base) under the request payload (override) — explicit run input always wins over remembered state.
4. **Session-end write-back** — `persist_session_results()`, invoked when a session reaches `END` or `ERROR`: for each declared organization path, compares the session's final variables against what's stored and writes back only the paths that changed. Runs inside `transaction.atomic()` with `select_for_update()` to serialize concurrent session-end writes for the same flow. Any exception here is logged and swallowed — a persistence failure must never fail session termination.
5. **Copy / new version** — `seed_for_copy()`: copying a flow, or creating a new flow from an old graph version, seeds a fresh `GraphOrganization` row from the copied start node's declared organization values.

## Scopes

| Scope | Stored in | Shared across | Status |
|---|---|---|---|
| `organization` | `GraphOrganization.persistent_variables` | all users running the same flow | implemented |
| `user` | `GraphOrganizationUser.persistent_variables` | only the specific user running the session | **not implemented** — model and declaration shape exist; no merge, seed, or write-back happens for this scope (`# TODO refactor to use user_variable` markers throughout `persistent_variables_service.py`) |

`Session.graph_user` is still resolved and populated from the runner's org membership so the foreign key is correct, but no user-scoped variable ever flows through it under the current design.

## Visibility

There is currently no API endpoint that exposes `GraphOrganization.persistent_variables` directly. The only ways to see the current remembered values are direct DB access, or indirectly by inspecting the merged variables of a freshly started session.

## Related

- Flow-authoring guidance (patterns, anti-patterns, examples) lives in `tables/services/flow_assistant/skills/flow-ddd/SKILL.md`.
