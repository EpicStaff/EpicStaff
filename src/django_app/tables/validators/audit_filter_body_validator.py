from rest_framework import serializers


# Mirrors SessionSearchRequest's own field set (src/auditor/app/controllers/
# query_routes.py) - keep these two in sync if that shape ever changes.
_FILTER_BODY_KEY_TYPES: dict[str, type] = {
    "filters": dict,
    "query": str,
    "match_scope": dict,
    "cursor": str,
    "size": int,
}


def validate_filter_body_shape(value):
    """
    filter_body must be a JSON object matching the search request body
    shape ({"filters": FilterNode} | {"query": str}, optionally with
    match_scope/cursor/size) - not just any dict. Checked here: known keys
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

    unknown_keys = set(value) - set(_FILTER_BODY_KEY_TYPES)
    if unknown_keys:
        raise serializers.ValidationError(
            f"filter_body has unrecognized key(s): {', '.join(sorted(unknown_keys))}. "
            f"Allowed keys: {', '.join(sorted(_FILTER_BODY_KEY_TYPES))}."
        )

    for key, expected_type in _FILTER_BODY_KEY_TYPES.items():
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
