"""User-actions-domain OpenAPI content: its field list and search-request examples."""

from app.domains.user_actions.fields import KNOWN_FIELDS

_FIELD_NAMES = ", ".join(f"`{name}`" for name in sorted(KNOWN_FIELDS) if not name.startswith("__"))

FILTERS_FIELD_DESCRIPTION = f"""
A `FilterNode` tree - the same shape produced by the query-language parser,
so `filters` and `query` are two front-ends for one identical AST:

    {{"op": "and" | "or", "children": [FilterNode, ...]}}
  | {{"op": "not", "child": FilterNode}}
  | {{"field": str, "op": str, "value": Any}}   # leaf - "value" omitted for is_empty/is_not_empty

**`filters` and `query` are mutually exclusive** - send exactly one, or neither for no filtering.

**Fields** (case-insensitive): {_FIELD_NAMES}.

Not every op is valid on every field - an invalid combination 400s with the allowed set for that field.
"""

USER_ACTION_SEARCH_REQUEST_DESCRIPTION = """See the `filters`/`query` field descriptions below for the full
AST shape, field list, and op vocabulary - `filters` and `query` are
two front-ends for the identical filter tree, never both in one request.
"""

SEARCH_REQUEST_EXAMPLES = {
    "deletions (query)": {
        "summary": "Everything deleted at once, moved to the recycle bin or deleted from it",
        "value": {"query": 'action in ("deleted", "moved_to_recycle_bin", "permanently_deleted")'},
    },
    "renames of a flow (filters)": {
        "summary": "Renames of flows, as an AST",
        "value": {
            "filters": {
                "op": "and",
                "children": [
                    {"field": "action", "op": "equals", "value": "renamed"},
                    {"field": "target_type", "op": "equals", "value": "flow"},
                ],
            }
        },
    },
    "one person's actions (query)": {
        "summary": "Actions by one email address, newest first",
        "value": {"query": 'actor_email = "user@example.com"'},
    },
    "record number range (query)": {
        "summary": "Records numbered 100 to 200",
        "value": {"query": "number >= 100 and number <= 200"},
    },
    "free text (query)": {
        "summary": "Bare word searches the email and name fields",
        "value": {"query": "onboarding"},
    },
}

SEARCH_USER_ACTIONS_DESCRIPTION = """
Org-wide search of what users did: creating, renaming, deleting and restoring
resources, plus sign-ins. Newest first.
"""
