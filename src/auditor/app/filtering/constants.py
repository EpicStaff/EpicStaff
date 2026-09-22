# Fields Allowed Filtering
TEXT_CONDITION_OPS = frozenset(
    {
        "equals",
        "contains",
        "starts_with",
        "ends_with",
        "not_contains",
        "not_equal",
        "is_empty",
        "is_not_empty",
    }
)
FLATTENED_OPS = frozenset(
    {
        "equals",
        "key_exists",
        "key_not_exists",
        "key_equals_value",
        "key_not_equals",
        "contains",
        "starts_with",
        "ends_with",
        "not_contains",
        "lt",
        "gt",
        "lte",
        "gte",
        "null",
        "not_null",
    }
)
SELECT_OPS = frozenset({"in", "not_in", "equals", "not_equal"})
RANGE_OPS = frozenset({"equals", "gt", "lt", "gte", "lte"})
DURATION_OPS = frozenset(
    {"gt", "lt", "gte", "lte", "equals", "is_empty", "is_not_empty"}
)
