🔎 Filtering & Query Language Reference

`POST /api/audit/sessions/search` (and the `POST` variant of
`/api/audit/sessions/{session_id}/tree`) take a request body with exactly one
of `filters` (a `FilterNode` AST) or `query` (this text language) — never
both. Both compile to the identical AST (`src/auditor/app/filtering/ast.py`),
so anything expressible in one is expressible in the other, **except** the
ops flagged "filters only" below, which have no query-language symbol.

See the request body's own `openapi_examples` in `/docs` (Swagger UI) for
runnable examples — one pair (query + filters) per op below, plus nesting
and `match_scope` examples. This doc is the reference; that's the
copy-paste starting point.

## Fields

| Field | Allowed ops |
|---|---|
| `kind` | `in`, `not_in`, `equals`, `not_equal` |
| `id` | those + `gt`, `lt`, `gte`, `lte` |
| `name` | `equals`, `not_equal`, `contains`, `not_contains`, `starts_with`, `ends_with`, `is_empty`, `is_not_empty` |
| `flow_name` | `in`, `not_in`, `equals`, `not_equal` |
| `node_type` | `in`, `not_in`, `equals`, `not_equal` |
| `status` | `in`, `not_in`, `equals`, `not_equal` |
| `event_time` | `equals`, `gt`, `lt`, `gte`, `lte` |
| `error` | same set as `name` (see `src/auditor/app/index_setup/README.md` for why `contains` must target `error.raw`, never analyzed `error`) |
| `run_type` | `in`, `not_in`, `equals`, `not_equal` |
| `duration` (computed - see below) | `gt`, `lt`, `gte`, `lte`, `equals`, `is_empty`, `is_not_empty` |
| `agent` (deep filter alias -> `details.agent_id`) | `in`, `not_in`, `equals`, `not_equal` |
| `tool` (-> `details.tool`) | `in`, `not_in`, `equals`, `not_equal` |
| `task` (-> `details.description`) | same set as `name` |
| `prompt` (-> `details.prompt_text`) | same set as `name` |
| `message_text` (-> `details.text`) | same set as `name` |
| `message_thought` (-> `details.thought`) | same set as `name` |
| `input` / `output` / `details`, bare or dotted (e.g. `details.retry_count`) | `equals`, `contains`, `not_contains`, `starts_with`, `ends_with`, `key_exists`, `key_not_exists`, `key_equals_value`, `key_not_equals`, `lt`, `gt`, `lte`, `gte`, `null`, `not_null` |
| *(bare word / `text:` prefix)* | free text - always `contains` against the `__text__` sentinel field |

Field names are matched case-insensitively. `duration` is computed from
paired Start/Finish-or-Error event timestamps — it is never sent to
OpenSearch directly, and it may only be combined with other conditions via
top-level `and` (never `or`/`not` — see `src/auditor/app/services/duration_filter.py`).

## Operators — query symbol → canonical AST `op`

| Query symbol | AST `op` | Notes |
|---|---|---|
| `=` or `==` | `equals` | |
| `!=` | `not_equal` | |
| `:` | `contains` | case-insensitive substring |
| `!:` | `not_contains` | |
| `>` | `gt` | |
| `<` | `lt` | |
| `>=` | `gte` | |
| `<=` | `lte` | |
| `in (a, b, c)` or `in [a, b, c]` | `in` | `(`/`)` and `[`/`]` are interchangeable |
| `not in (...)` | `not_in` | |
| `is empty` | `is_empty` | no `value` |
| `is not empty` | `is_not_empty` | no `value` |
| *(no symbol — filters only)* | `starts_with`, `ends_with`, `key_exists`, `key_not_exists`, `key_equals_value`, `key_not_equals`, `null`, `not_null` | send these as `filters` |

## Keywords

- `and`, `or`, `not` — boolean composition
- `( )` — grouping/nesting, unlimited depth, works identically in both forms
- `is`, `empty` — only meaningful as `is empty` / `is not empty`
- `in`, `not` — only meaningful as `in (...)` / `not in (...)`
- `text:` — explicit free-text prefix (a bare word alone has the same effect)

## Grammar (`src/auditor/app/filtering/query_language.py`)

```
expr        := or_expr
or_expr     := and_expr ("or" and_expr)*
and_expr    := unary ("and" unary)*
unary       := "not" unary | atom
atom        := "(" expr ")" | comparison | free_text
comparison  := IDENT ( "=" | "==" | "!=" | ":" | "!:" | ">" | "<" | ">=" | "<=" ) value
             | IDENT ("in" | "not" "in") ("(" | "[") value ("," value)* (")" | "]")
             | IDENT "is" ("not")? "empty"
free_text   := ("text" ":")? (STRING | NUMBER | IDENT)
value       := STRING | NUMBER | IDENT
```

Quoting: string values need `"..."`. A literal `"` inside a value is escaped
as `\"` in the query text — and once more if the query text itself travels
inside a JSON string in the request body. Example: matching
`details.expression` against the literal string `variables.yesno2 ==
"Yes"`:

- Query text: `details.expression == "variables.yesno2 == \"Yes\""`
- As a JSON request body: `{"query": "details.expression == \"variables.yesno2 == \\\"Yes\\\"\""}`

## Working with dates (`event_time`)

`event_time`'s value is passed straight through into an OpenSearch `range`
query — the auditor does no parsing/validation of it beyond the generic
range-op check. It accepts anything OpenSearch's `date` field accepts:

| Format | Example |
|---|---|
| ISO-8601 datetime | `"2026-08-01T00:00:00Z"` |
| Date-only | `"2026-08-01"` (midnight UTC) |
| Epoch millis | `1785628800000` (unquoted number) |
| OpenSearch date math | `"now-7d"`, `"now-1h"`, `"now/d"` |

A single leaf is one-sided (`gt`/`lt`/`gte`/`lte`/`equals` only) — a range
between two dates needs two leaves ANDed together:

```
event_time >= "2026-08-01" and event_time < "2026-08-10"
```

```json
{
  "op": "and",
  "children": [
    {"field": "event_time", "op": "gte", "value": "2026-08-01"},
    {"field": "event_time", "op": "lt", "value": "2026-08-10"}
  ]
}
```

Quote the date in the query language — a bare `2026-08-01` isn't a valid
`IDENT`/`NUMBER` token (the dashes break tokenization).

## Nesting

Parentheses (query) / nested `and`/`or`/`not` nodes (filters) compose to
unlimited depth — a child of `and`/`or` can itself be another `and`/`or`/`not`
node, and so on.

Query:
```
(status = "failed" or status = "error")
and (tool = "Web Search Tool" or agent = "Researcher")
and not duration < 10
```

Equivalent filters AST:
```json
{
  "op": "and",
  "children": [
    {
      "op": "or",
      "children": [
        {"field": "status", "op": "equals", "value": "failed"},
        {"field": "status", "op": "equals", "value": "error"}
      ]
    },
    {
      "op": "or",
      "children": [
        {"field": "tool", "op": "equals", "value": "Web Search Tool"},
        {"field": "agent", "op": "equals", "value": "Researcher"}
      ]
    },
    {
      "op": "not",
      "child": {"field": "duration", "op": "lt", "value": 10}
    }
  ]
}
```

## `match_scope` — structural, not a filter condition

Reshapes which rows come back around a match; sent alongside `filters`/`query`
in the same request body, never inside the AST itself.

| Field | Effect |
|---|---|
| `ancestors: true` | pull in the match's owning node/session wrapper doc(s), up to 2 hops |
| `children: true` | a matched session pulls in its whole tree; a matched node pulls in its own events |
| `rows_before: N` (max 20) | include the N rows immediately preceding each match, same session |
| `full_session_history: true` | supersedes the other three — full unfiltered session tree for every matched session |

## Worked examples

```
status in ["failed", "error"] and tool = "Web Search Tool"
name : "Session" and not duration < 10
(status = "failed" or status = "error") and (agent = "Researcher" or tool = "Notification Tool")
error is not empty
details.expression == "variables.yesno2 == \"Yes\""
text: timeout
```
