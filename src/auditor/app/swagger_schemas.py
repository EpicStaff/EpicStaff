"""
Generic, domain-free OpenAPI/Swagger documentation content for the
auditor service - tag descriptions and the AST/query-language grammar
docs that apply to every domain, not scattered across
`main.py`/`app/controllers/*.py`. Route and model files import from this
module and stay focused on behavior.

Sessions-specific swagger content (the field-list description, search
request examples, match_scope/search-endpoint descriptions - anything
that names sessions' own fields/aliases) lives in
`app/domains/sessions/docs.py` instead. A future second domain gets its
own `app/domains/<name>/docs.py` sibling rather than a growing pile of
domain-specific constants here.
"""

# --- app/main.py ------------------------------------------------------
#
# Tag order here is the order the groups appear in /docs. Each description
# states which of the two authentication schemes the group uses, because
# that is the least obvious thing about this API: producers authenticate
# with a static shared key, end users with a short-lived token minted
# elsewhere.
OPENAPI_TAGS = [
    {
        "name": "Browse",
        "description": (
            "Read the audit trail. **Auth: `HTTPBearer`** - the short-lived (5 min) "
            "JWT from django_app's `POST /api/audit/token/`, which requires the "
            "`read` action in its `actions` claim. Results are always scoped to "
            "the token's `org_id` and clipped to its `retention_days` window; "
            "neither can be widened by any request parameter."
        ),
    },
    {
        "name": "Export",
        "description": (
            "Export the audit trail as CSV or JSON. **Auth: `HTTPBearer`** with the "
            "`export` action - gated independently of `read`, so a token may browse "
            "without being able to export.\n\n"
            "Asynchronous: `POST` returns a `job_id`, then poll `GET .../{job_id}`, "
            'which answers `{"status": "pending"}` as JSON until the job '
            "finishes and then serves the file body itself (`500` if it failed)."
        ),
    },
    {
        "name": "Ingest",
        "description": (
            "Write endpoint for producer services (crew, django_app), not for end "
            "users. **Auth: `APIKeyHeader`** - the static `X-API-Key` shared secret, "
            "not a user token.\n\n"
            "Idempotent: each event carries its own `id`, which becomes the "
            "OpenSearch document `_id`, so re-sending a batch overwrites in place "
            "instead of duplicating. This is what makes the client's retry path safe."
        ),
    },
    {
        "name": "Health",
        "description": "Liveness probe. Unauthenticated.",
    },
]

# --- app/controllers/query_routes.py -----------------------------------

QUERY_FIELD_DESCRIPTION = """
Textual alternative to `filters` - parses to the identical AST. Grammar:
`field OP value`, combined with `and`/`or`/`not`, parenthesized for grouping.

Operators, and the canonical AST op each parses to: `=`/`==` -> `equals`,
`!=` -> `not_equal`, `:` -> `contains`, `!:` -> `not_contains`, `>` -> `gt`,
`<` -> `lt`, `>=` -> `gte`, `<=` -> `lte`, `in (a, b, c)`/`in [a, b, c]` ->
`in`, `not in (...)` -> `not_in`, `is empty` -> `is_empty`, `is not empty` ->
`is_not_empty`. Free text: a bare word, or `text: <term>`, searches everywhere
(-> `{"field": "__text__", "op": "contains", ...}`).

**Query-language-only ops** (no symbol exists for these - use `filters` (AST)
instead): `starts_with`, `ends_with`, `key_exists`, `key_not_exists`,
`key_equals_value`, `key_not_equals`, `null`, `not_null`. These only apply to
flattened `input`/`output`/`details` paths anyway, where free-text `:`/`!:`
usually covers the same need.

A literal `"` inside a quoted value must be escaped as `\\"` (and, once
more, for the JSON string this whole query travels in as - e.g. to match
`details.expression` against the literal string `variables.yesno2 ==
"Yes"`, the query text is `details.expression == "variables.yesno2 ==
\\"Yes\\""`, sent as JSON `"details.expression == \\"variables.yesno2 == \\\\\\"Yes\\\\\\"\\""`).

Examples (grammar coverage - not every field/op combo is meaningful together,
see the per-op pairs in this request's own `openapi_examples`):
    status in ["error", "warning"] or tool in ["Web Search Tool", "Notification Tool"]
    name == "Session Start"
    Error is not empty and not ID == 66
    input : est3285 and output : Greetings
    status != "completed" and duration >= 60
    text: "timeout"
"""

CURSOR_FIELD_DESCRIPTION = (
    "Opaque pagination cursor from a previous response's `next_cursor`."
)
SIZE_FIELD_DESCRIPTION = "Max rows per page (<=1000)."
