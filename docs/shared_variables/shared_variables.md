# Shared Variables

**Source:** `src/crew/services/graph/shared_variables.py`

## Problem

When multiple sessions run concurrently for the same chat (e.g. rapid-fire messages triggering leader/follower orchestration), they need to:

1. **Share state** — multiple sessions read/write the same variables (inbox, active_followers, lease_holder)
2. **Isolate by context** — different chats get separate variable instances
3. **Synchronize immediately** — a follower's write must be visible to the leader within the same execution
4. **Clean up automatically** — variables expire when no sessions need them

Regular session variables (`variables.<name>`) are scoped to a single session. Persistent variables (`variables.persistent.<name>`) survive across sessions but aren't readable by concurrent sessions during execution.

## Solution

A `variables.shared` namespace backed by Redis. Proxy objects (`SharedVariables` → `SharedVariableScope`) intercept attribute access to transparently load from and write to Redis. Mutable types (list, dict) are wrapped with observable proxies so mutations like `.append()` trigger automatic write-through. All of this is synchronous from the user's perspective — no `await` needed in node code.

## Access Pattern

```python
variables.shared[access_key].variable_name
```

- **Access key** scopes variables by context (e.g. `chat_id`). Related sessions use the same key to share state; different keys isolate state.
- **Read**: lazy-loads from Redis on first access, cached for session duration.
- **Write**: immediate write-through to Redis on every assignment or mutation.
- **Cleanup**: session metadata cleaned when all sessions complete; variable data expires via TTL (1 hour default).

## Atomic Operations

Beyond simple get/set, `SharedVariableScope` provides two atomic primitives used by CDT pre-computation via special return keys:

- **`scope.claim(name, value, ttl=None)`** — Redis `SET NX` (first-writer-wins). Returns `True` if this call set the value. Used for leader election.
- **`scope.atomic_list_append(name, items)`** — Redis lock-based read-modify-write for shared lists. Avoids race conditions when multiple sessions append concurrently.

CDT pre-computation triggers these via return dict keys `shared_claim` and `shared_append` (handled in `_execute_computation`).

## Observable Wrappers

`ObservableList` and `ObservableDict` wrap mutable values so mutations (`.append()`, `[key] =`, `.pop()`, etc.) trigger automatic write-through to Redis. User code works with normal list/dict operations — no special API needed.

## Start Node Initialization

Shared scopes can be pre-initialized in StartNode variables using template interpolation:

```json
{
  "chat_id": "{chat_id:test_123}",
  "shared": {
    "{chat_id:test_123}": {
      "init_defaults": true,
      "counter": 0,
      "inbox_messages": []
    }
  }
}
```

- Templates like `{chat_id:default}` are resolved from user-provided variables (API call or flow designer).
- `init_defaults: true` — only sets variables that don't already exist (prevents overwriting concurrent sessions).
- The `shared` dict is **not persisted** to the database — it's internal initialization only.

## Input Mapping

Input maps support dynamic access keys and default values:

```json
{
  "input_map": {
    "followers": "variables.shared[variables.chat_id].active_followers|[]",
    "inbox": "variables.shared[variables.chat_id].inbox_messages|[]"
  }
}
```

- `variables.chat_id` is resolved first, then used as the access key.
- `|[]` provides a default if the variable doesn't exist yet — no `None` checks needed in user code.

## Output Mapping

### Bulk updates (scope-level)

```python
def main(chat_id: str) -> dict:
    return {
        "shared": {
            chat_id: {
                "init_defaults": True,
                "counter": 0,
                "active_followers": []
            }
        }
    }
```

### Individual variable

With `output_variable_path: variables.shared[chat_id].active_followers`:

```python
def main(session_id: str) -> dict:
    return {"active_followers": [{"session_id": session_id}]}
```

## Serialization

The `shared` proxy is infrastructure, filtered out everywhere:

- **DB storage** — `session_manager_service.py` strips `shared` key before persisting
- **API responses** — `SessionSerializer` strips it from JSON output
- **SSE/WebSocket** — `graph_session_manager_service.py` strips it before broadcasting
- **JSON encoding** — monkey-patched `json.JSONEncoder.default` serializes `SharedVariables`/`SharedVariableScope` as `{}` and `ObservableList`/`ObservableDict` as plain `list`/`dict`

## Redis Data Model

```
shared_var:{access_key}:{name}:data       → JSON string (TTL 1h)
shared_var:{access_key}:{name}:sessions   → Set of session IDs
session:{session_id}:status               → "active" | "completed" | "failed"
session:{session_id}:variables            → Set of var_id strings
```

## Cleanup

On session end, `cleanup_session()` marks the session as completed and checks if any other sessions are still active for each variable. If none are active, **session metadata** is deleted. **Variable data is NOT eagerly deleted** — TTL handles expiration. This prevents a race where a later session (e.g. leader at end-stage) still needs data written by a now-finished session.

## Cache Management

`SharedVariableScope._clear_cache()` drops all cached values, forcing the next access to re-read from Redis. Used by CDT two-phase pre-computation when `needs_rerun` is set — ensures the second phase sees values written by `shared_claim`/`shared_append` in the first phase.
