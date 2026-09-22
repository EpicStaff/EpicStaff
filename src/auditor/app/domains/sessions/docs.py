"""
Sessions-domain OpenAPI/Swagger content: everything that names sessions'
own fields, deep-filter aliases, or search-request examples. Domain-free
docs content (tag descriptions, the AST/query-language grammar,
cursor/size field docs) stays in `app/swagger_schemas.py` - see that
module's docstring for the split rationale.

`build_filters_field_description` takes a `FieldCatalog` (see
app/domains/base.py) rather than being a static string baked in at
import time - that deferred-computation shape is what a second domain's
own docs module would replicate. Today it still reaches past the
Protocol into this module's own `KNOWN_FIELDS` to list concrete field
names, because `FieldCatalog` only exposes per-field lookups
(`field_spec`, `resolve_alias`, ...), not "list every known field" -
adding that would mean widening the Protocol, out of scope for this
split. Flagged here rather than silently assumed.
"""

from app.domains.base import FieldCatalog
from app.domains.sessions.fields import KNOWN_FIELDS, SESSIONS_FIELDS


def build_filters_field_description(catalog: FieldCatalog) -> str:
    known_field_names = sorted(f for f in KNOWN_FIELDS if not f.startswith("__"))
    return f"""
A `FilterNode` tree - the same shape produced by the query-language parser,
so `filters` and `query` are two front-ends for one identical AST:

    {{"op": "and" | "or", "children": [FilterNode, ...]}}
  | {{"op": "not", "child": FilterNode}}
  | {{"field": str, "op": str, "value": Any}}   # leaf - "value" omitted for is_empty/is_not_empty

**`filters` and `query` are mutually exclusive** - send exactly one, or neither for no filtering.

**Fields** (case-insensitive): {", ".join(f"`{f}`" for f in known_field_names)},
plus any dotted path into the free-form blobs: `input.<key>`, `output.<key>`,
`details.<key>` (or the bare root `input`/`output`/`details` to search the whole blob).

**Ops**: `equals`, `not_equal`, `in`, `not_in`, `gt`, `lt`, `gte`, `lte`, `contains`,
`not_contains`, `starts_with`, `ends_with`, `is_empty`, `is_not_empty` (structured/text
fields); `key_exists`, `key_not_exists`, `key_equals_value`, `key_not_equals`, `null`,
`not_null` (flattened `input`/`output`/`details` paths only). Not every op is valid on
every field - an invalid combination 400s with the allowed set for that field.

**`duration`** is computed (paired Start/Finish event timestamps), not an indexed
field - it may only be combined with other conditions via top-level `and` (never
`or`/`not`).

Example leaf: `{{"field": "status", "op": "in", "value": ["failed", "error"]}}`
"""


FILTERS_FIELD_DESCRIPTION = build_filters_field_description(SESSIONS_FIELDS)

MATCH_SCOPE_FIELD_DESCRIPTION = (
    "Structural toggles - reshape which rows come back, not filter conditions."
)

SESSION_SEARCH_REQUEST_DESCRIPTION = """See the `filters`/`query` field descriptions below for the full
AST shape, field list, and op vocabulary - `filters` and `query` are
two front-ends for the identical filter tree, never both in one request.
"""

SEARCH_REQUEST_EXAMPLES = {
    # --- General / combined ------------------------------------------
    "all sessions": {
        "summary": "Every session (kind=session), newest first",
        "value": {"filters": {"field": "kind", "op": "in", "value": ["session"]}},
    },
    "and/or/not (query)": {
        "summary": "Boolean composition - failed rows mentioning a specific tool",
        "value": {"query": 'status = "failed" and tool = "Web Search Tool"'},
    },
    "and/or/not (filters)": {
        "summary": "Same boolean composition, as an AST",
        "value": {
            "filters": {
                "op": "and",
                "children": [
                    {"field": "status", "op": "equals", "value": "failed"},
                    {"field": "tool", "op": "equals", "value": "Web Search Tool"},
                ],
            }
        },
    },
    "not (query)": {
        "summary": "Negation via `not`",
        "value": {"query": 'not status = "failed"'},
    },
    "not (filters)": {
        "summary": "Same negation, as an AST",
        "value": {
            "filters": {
                "op": "not",
                "child": {"field": "status", "op": "equals", "value": "failed"},
            }
        },
    },
    "nested groups (query)": {
        "summary": "Parenthesized sub-expressions, arbitrarily deep",
        "value": {
            "query": (
                '(status = "failed" or status = "error") '
                'and (tool = "Web Search Tool" or agent = "Researcher") '
                "and not duration < 10"
            )
        },
    },
    "nested groups (filters)": {
        "summary": "Same nesting as an AST - and/or nodes hold a 'children' list of nodes, not/child holds one node; any child can itself be another and/or/not",
        "value": {
            "filters": {
                "op": "and",
                "children": [
                    {
                        "op": "or",
                        "children": [
                            {"field": "status", "op": "equals", "value": "failed"},
                            {"field": "status", "op": "equals", "value": "error"},
                        ],
                    },
                    {
                        "op": "or",
                        "children": [
                            {
                                "field": "tool",
                                "op": "equals",
                                "value": "Web Search Tool",
                            },
                            {"field": "agent", "op": "equals", "value": "Researcher"},
                        ],
                    },
                    {
                        "op": "not",
                        "child": {"field": "duration", "op": "lt", "value": 10},
                    },
                ],
            }
        },
    },
    # --- equals / not_equal --------------------------------------------
    "equals (query)": {
        "summary": "op: equals - `=`/`==`",
        "value": {"query": 'status = "failed"'},
    },
    "equals (filters)": {
        "summary": "op: equals",
        "value": {"filters": {"field": "status", "op": "equals", "value": "failed"}},
    },
    "not_equal (query)": {
        "summary": "op: not_equal - `!=`",
        "value": {"query": 'status != "completed"'},
    },
    "not_equal (filters)": {
        "summary": "op: not_equal",
        "value": {
            "filters": {"field": "status", "op": "not_equal", "value": "completed"}
        },
    },
    # --- contains / not_contains ----------------------------------------
    "contains (query)": {
        "summary": "op: contains - `:`, case-insensitive substring",
        "value": {"query": 'output : "timeout"'},
    },
    "contains (filters)": {
        "summary": "op: contains",
        "value": {"filters": {"field": "output", "op": "contains", "value": "timeout"}},
    },
    "not_contains (query)": {
        "summary": "op: not_contains - `!:`",
        "value": {"query": 'output !: "timeout"'},
    },
    "not_contains (filters)": {
        "summary": "op: not_contains",
        "value": {
            "filters": {"field": "output", "op": "not_contains", "value": "timeout"}
        },
    },
    # --- starts_with / ends_with (filters-only - no query symbol) -------
    "starts_with (filters only)": {
        "summary": "op: starts_with - no query-language symbol, use filters",
        "value": {
            "filters": {"field": "name", "op": "starts_with", "value": "Session"}
        },
    },
    "ends_with (filters only)": {
        "summary": "op: ends_with - no query-language symbol, use filters",
        "value": {"filters": {"field": "name", "op": "ends_with", "value": "Finish"}},
    },
    # --- is_empty / is_not_empty -----------------------------------------
    "is_empty (query)": {
        "summary": "op: is_empty - `is empty`",
        "value": {"query": "error is empty"},
    },
    "is_empty (filters)": {
        "summary": "op: is_empty (no 'value' key)",
        "value": {"filters": {"field": "error", "op": "is_empty"}},
    },
    "is_not_empty (query)": {
        "summary": "op: is_not_empty - `is not empty`",
        "value": {"query": "error is not empty"},
    },
    "is_not_empty (filters)": {
        "summary": "op: is_not_empty (no 'value' key)",
        "value": {"filters": {"field": "error", "op": "is_not_empty"}},
    },
    # --- in / not_in --------------------------------------------------
    "in (query)": {
        "summary": "op: in - `in (a, b)` or `in [a, b]`",
        "value": {"query": 'status in ["failed", "error"]'},
    },
    "in (filters)": {
        "summary": "op: in",
        "value": {
            "filters": {"field": "status", "op": "in", "value": ["failed", "error"]}
        },
    },
    "not_in (query)": {
        "summary": "op: not_in - `not in (...)`",
        "value": {"query": 'status not in ["failed", "error"]'},
    },
    "not_in (filters)": {
        "summary": "op: not_in",
        "value": {
            "filters": {"field": "status", "op": "not_in", "value": ["failed", "error"]}
        },
    },
    # --- gt / lt / gte / lte -----------------------------------------
    "gt/lt/gte/lte (query)": {
        "summary": "Range ops on a computed field - `duration > 1800` (seconds)",
        "value": {"query": "duration > 1800"},
    },
    "gt/lt/gte/lte (filters)": {
        "summary": "Same range comparison, as an AST",
        "value": {"filters": {"field": "duration", "op": "gt", "value": 1800}},
    },
    "event_time range (query)": {
        "summary": "Dates as quoted ISO-8601 strings - bare dates aren't a valid token",
        "value": {"query": 'event_time >= "2026-08-01" and event_time < "2026-08-10"'},
    },
    "event_time range (filters)": {
        "summary": "Same date range, as an AST - two ANDed leaves (one leaf is one-sided)",
        "value": {
            "filters": {
                "op": "and",
                "children": [
                    {"field": "event_time", "op": "gte", "value": "2026-08-01"},
                    {"field": "event_time", "op": "lt", "value": "2026-08-10"},
                ],
            }
        },
    },
    "event_time date-math (query)": {
        "summary": "OpenSearch date-math value, evaluated at query time",
        "value": {"query": 'event_time > "now-7d"'},
    },
    # --- free text ------------------------------------------------------
    "free text - bare word (query)": {
        "summary": "Bare word searches every field",
        "value": {"query": "timeout"},
    },
    "free text - text: prefix (query)": {
        "summary": "Explicit `text:` prefix, same effect as a bare word",
        "value": {"query": "text: timeout"},
    },
    "free text (filters)": {
        "summary": "Free text as an AST leaf - sentinel field `__text__`",
        "value": {
            "filters": {"field": "__text__", "op": "contains", "value": "timeout"}
        },
    },
    # --- deep filters (agent/tool/task/prompt/message_text/message_thought) ---
    "deep filter - agent (query)": {
        "summary": "Deep filter alias `agent` -> details.agent_id",
        "value": {"query": 'agent in ["Researcher", "Writer"]'},
    },
    "deep filter - tool (filters)": {
        "summary": "Deep filter alias `tool` -> details.tool",
        "value": {
            "filters": {"field": "tool", "op": "in", "value": ["Web Search Tool"]}
        },
    },
    "deep filter - prompt (query)": {
        "summary": "Deep filter alias `prompt` -> details.prompt_text (free text)",
        "value": {"query": 'prompt : "summarize"'},
    },
    # --- flattened input/output/details paths (filters-only ops) --------
    "key_exists (filters only)": {
        "summary": "op: key_exists - a specific key under a flattened blob",
        "value": {"filters": {"field": "details.retry_count", "op": "key_exists"}},
    },
    "key_not_exists (filters only)": {
        "summary": "op: key_not_exists",
        "value": {"filters": {"field": "details.retry_count", "op": "key_not_exists"}},
    },
    "key_equals_value (filters only)": {
        "summary": "op: key_equals_value - exact match on a flattened key's value",
        "value": {
            "filters": {
                "field": "details.retry_count",
                "op": "key_equals_value",
                "value": 3,
            }
        },
    },
    "key_not_equals (filters only)": {
        "summary": "op: key_not_equals",
        "value": {
            "filters": {
                "field": "details.retry_count",
                "op": "key_not_equals",
                "value": 3,
            }
        },
    },
    "null (filters only)": {
        "summary": "op: null - flattened key is JSON null (distinct from key_not_exists)",
        "value": {"filters": {"field": "details.error_code", "op": "null"}},
    },
    "not_null (filters only)": {
        "summary": "op: not_null",
        "value": {"filters": {"field": "details.error_code", "op": "not_null"}},
    },
    "flattened path - whole blob (query)": {
        "summary": "Bare `input`/`output`/`details` root - search anywhere in the blob",
        "value": {"query": "input : est3285 and output : Greetings"},
    },
    # --- match_scope (structural, filters/query field either way) -------
    "match_scope - full_session_history": {
        "summary": "Expand every match to its full, unfiltered session tree",
        "value": {
            "query": "error is not empty",
            "match_scope": {"full_session_history": True},
        },
    },
    "match_scope - ancestors": {
        "summary": "Pull in each match's owning node/session wrapper doc(s)",
        "value": {"query": "error is not empty", "match_scope": {"ancestors": True}},
    },
    "match_scope - children": {
        "summary": "A matched session/node pulls in its own children too",
        "value": {
            "filters": {"field": "kind", "op": "in", "value": ["session"]},
            "match_scope": {"children": True},
        },
    },
    "match_scope - rows_before": {
        "summary": "Include the 5 rows immediately preceding each match, same session",
        "value": {"query": "error is not empty", "match_scope": {"rows_before": 5}},
    },
}

SEARCH_SESSIONS_DESCRIPTION = """
Org-wide (all flows) session search - filter/query-driven replacement
for the old `GET /api/audit/sessions`. `kind="session"` is no longer an
implicit default - send it explicitly (e.g. `{"field": "kind", "op":
"in", "value": ["session"]}`) if that's what the caller wants.
"""
