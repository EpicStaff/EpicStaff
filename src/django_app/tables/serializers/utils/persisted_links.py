from tables.services.secrets.linked_ids import linked_ids


def current_linked_ids(*, serializer, source) -> frozenset:
    """Return the pks the persisted row links to through `source`, binned rows included.

    A row in the recycle bin keeps the links to it until it's purged, so saving the
    linking row unchanged must keep such a link: KeptLinkPrimaryKeyRelatedField accepts
    exactly these pks on top of the live rows.

    A nested serializer has no instance of its own, so the persisted value is read
    through its hooks: `get_current_secret_reference(source)` when declared, else its
    `parent_attribute` on the parent serializer's instance, else its own instance.
    """
    return linked_ids(_current_value(serializer=serializer, source=source))


def _current_value(*, serializer, source):
    hook = getattr(serializer, "get_current_secret_reference", None)
    if hook is not None:
        return hook(source)
    parent_attribute = getattr(serializer, "parent_attribute", None)
    if parent_attribute is not None:
        parent_instance = getattr(serializer.parent, "instance", None)
        current = (
            getattr(parent_instance, parent_attribute, None)
            if parent_instance is not None
            else None
        )
        return getattr(current, source, None) if current is not None else None
    return getattr(serializer.instance, source, None)
