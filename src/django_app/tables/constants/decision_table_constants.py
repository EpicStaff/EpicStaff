# Columns a Decision Table node's condition groups and conditions take from input.
# Both write paths (the single-node viewset and graph bulk save) build these rows from
# request dicts that no serializer has validated, so they copy only these keys and set the
# parent FK themselves. An allow-list rather than a denylist: a parent FK attname
# (`decision_table_node_id`, `condition_group_id`) or a bookkeeping column such as
# `is_soft_deleted` can never be mass-assigned from the request.
CONDITION_GROUP_INPUT_FIELDS = frozenset(
    {"group_name", "group_type", "order", "expression", "manipulation", "next_node_id"}
)

CONDITION_INPUT_FIELDS = frozenset({"condition_name", "order", "condition"})
