from rest_framework import serializers

from tables.models.audit_filter_preset_models import AuditPresetDomain

# Mirror each domain's auditor search request (src/auditor/app/domains/sessions/
# schemas.py SessionSearchRequest, .../user_actions/schemas.py
# UserActionSearchRequest) - keep them in sync if those shapes ever change -
# plus `ui_state`, the frontend's own panel state. `ui_state` is never sent
# to the auditor (its request models forbid extra keys); the frontend strips
# it before searching and only uses it to restore the filters panel.
_USER_ACTIONS_KEY_TYPES: dict[str, type] = {
    "filters": dict,
    "query": str,
    "cursor": str,
    "size": int,
    "ui_state": dict,
}
_FILTER_BODY_KEY_TYPES: dict[str, dict[str, type]] = {
    AuditPresetDomain.SESSIONS: {**_USER_ACTIONS_KEY_TYPES, "match_scope": dict},
    AuditPresetDomain.USER_ACTIONS: _USER_ACTIONS_KEY_TYPES,
}


def validate_filter_body_shape(value, domain: str):
    """
    filter_body must be a JSON object matching `domain`'s search request body
    shape ({"filters": FilterNode} | {"query": str}, optionally with
    cursor/size, and match_scope for sessions), plus an optional frontend-only
    `ui_state` object - not just any dict. Checked here: known keys
    only, and each present key has the right JSON type. NOT checked here:
    the actual FilterNode/query-language grammar inside `filters`/`query`
    (field names, ops, values) - that only happens once, at search time, in
    `auditor` (django_app has no import path to auditor's AST module and
    isn't meant to grow one just for this). This layer exists to catch
    structural mistakes - a bare string, an unrelated/misspelled key, a
    wrong-typed value - immediately, not a preset that "looks like" a
    filter but 400s every time it's actually used to search.
    """
    if not isinstance(value, dict):
        raise serializers.ValidationError(
            "filter_body must be a JSON object matching the search request body "
            "shape (e.g. {'filters': {...}} or {'query': '...'}), not a bare value."
        )

    key_types = _FILTER_BODY_KEY_TYPES[domain]
    unknown_keys = set(value) - set(key_types)
    if unknown_keys:
        raise serializers.ValidationError(
            f"filter_body has unrecognized key(s): {', '.join(sorted(unknown_keys))}. "
            f"Allowed keys: {', '.join(sorted(key_types))}."
        )

    for key, expected_type in key_types.items():
        if key in value and not isinstance(value[key], expected_type):
            raise serializers.ValidationError(
                f"filter_body.{key} must be a {expected_type.__name__}, "
                f"got {type(value[key]).__name__}."
            )

    if value.get("filters") is not None and value.get("query") is not None:
        raise serializers.ValidationError(
            "filter_body cannot set both 'filters' and 'query' - they are "
            "mutually exclusive, same as the search request body."
        )
    return value
