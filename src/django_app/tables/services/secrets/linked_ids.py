def linked_ids(value) -> frozenset:
    """Collapse what a field links to into one comparable set of pks.

    Accepts None, a single row (a Secret or a WebhookTrigger), a raw pk, a related
    manager, or a list/tuple/set of rows or pks. A related manager is read through
    `all_objects`: a row in the recycle bin keeps the links to it until it's purged,
    so it still counts as linked.
    """
    if value is None:
        return frozenset()
    if hasattr(value, "all"):
        rows = value(manager="all_objects") if callable(value) else value
        return frozenset(row.pk for row in rows.all())
    if isinstance(value, (list, tuple, set, frozenset)):
        return frozenset(getattr(item, "pk", item) for item in value)
    return frozenset({getattr(value, "pk", value)})
