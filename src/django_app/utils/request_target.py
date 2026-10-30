"""What a resolved request names: its route as a URL path pattern, and the object in its URL.

Shared by the records written after a response (plugin activity, the user-action
fallback), which know the request only by its route and URL kwargs, never by its body.
"""

import re

from django.db.models import Model

# URL kwargs a detail route names its object by.
TARGET_URL_KWARGS = ("pk", "id")
# The columns a row is labelled with, the first one its model has.
TARGET_LABEL_FIELDS = ("name", "custom_name")
_NAMED_GROUP_START = re.compile(r"\(\?P<(\w+)>")
_PATH_CONVERTER = re.compile(r"<\w+:(\w+)>")


def url_path_pattern(route: str) -> str:
    """A resolved route as a URL path pattern, the same form for every view.

    A router's regular expressions lose their anchors and escapes, and each named group
    becomes `<name>`: `api/^graphs/(?P<pk>[^/.]+)/$` is recorded as `api/graphs/<pk>/`. A
    `path()` route loses its converters the same way: `api/sessions/<int:session_id>/stop/`
    is recorded as `api/sessions/<session_id>/stop/`.
    """
    parts = []
    position = 0
    while (group := _NAMED_GROUP_START.search(route, position)) is not None:
        parts.append(route[position : group.start()])
        parts.append(f"<{group.group(1)}>")
        position = _end_of_group(route, group.end())
    parts.append(route[position:])
    pattern = re.sub(r"\\(.)", r"\1", "".join(parts).replace("^", "").replace("$", ""))
    return _PATH_CONVERTER.sub(r"<\1>", pattern)


def _end_of_group(route: str, position: int) -> int:
    """The position after the parenthesis that closes the group open before `position`."""
    depth = 1
    while position < len(route) and depth:
        character = route[position]
        if character == "\\":
            position += 1
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        position += 1
    return position


def target_from_url(
    view_class, match, org_id: int, label_fields: tuple[str, ...] = TARGET_LABEL_FIELDS
) -> tuple[str, str | None] | None:
    """The object a detail route names, labelled when the organization still has it.

    Args:
        label_fields: The columns the label may come from; the first one the model has
            is read, and an empty value is no label.
    """
    kwargs = match.kwargs if match is not None else {}
    value = next((kwargs[name] for name in TARGET_URL_KWARGS if name in kwargs), None)
    if value is None:
        return None
    return str(value), _label_of_row(view_class, value, org_id, label_fields)


def _label_of_row(view_class, value, org_id: int, label_fields: tuple[str, ...]) -> str | None:
    """The row's label, read in `org_id` only, so a label never comes from another
    organization's row; None for a model without an organization."""
    model = model_of(view_class)
    if model is None:
        return None
    field_names = {field.name for field in model._meta.concrete_fields}
    label_field = next((name for name in label_fields if name in field_names), None)
    if "org" not in field_names or label_field is None:
        return None
    try:
        label = (
            model._base_manager.filter(pk=value, org_id=org_id)
            .values_list(label_field, flat=True)
            .first()
        )
    except (TypeError, ValueError):
        return None
    return label if isinstance(label, str) and label else None


def model_of(view_class) -> type[Model] | None:
    """The model a view serves: its queryset's, else its serializer's."""
    queryset = getattr(view_class, "queryset", None)
    if queryset is not None:
        return queryset.model
    serializer_meta = getattr(getattr(view_class, "serializer_class", None), "Meta", None)
    return getattr(serializer_meta, "model", None)
