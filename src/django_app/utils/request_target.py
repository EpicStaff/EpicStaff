"""What a resolved request names: its route as a URL path pattern, and the object in its URL
or, for a create, the id its response names.

Shared by the records written after a response (plugin activity, the user-action
fallback), which know the request only by its route and URL kwargs, never by its body.
"""

import re
from collections.abc import Iterable, Mapping

from django.core.exceptions import ValidationError
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
    value = id_from_url(match)
    if value is None:
        return None
    return str(value), _label_of_row(view_class, value, org_id, label_fields)


def id_from_url(match):
    """The `pk` or `id` URL kwarg a detail route names its object by, or None."""
    kwargs = match.kwargs if match is not None else {}
    return next((kwargs[name] for name in TARGET_URL_KWARGS if name in kwargs), None)


def id_from_response(model: type[Model], data):
    """The id a create response names its object by, or None.

    Reads only that key of the response: `pk`, `id`, or the model's own primary key (a
    one-to-one child such as voice settings is keyed by its parent, `agent_definition`).
    """
    if not isinstance(data, Mapping):
        return None
    primary_key = model._meta.pk
    keys = (*TARGET_URL_KWARGS, primary_key.name, primary_key.attname)
    return next((data[key] for key in keys if key in data), None)


def org_row(view_class, value, org_id: int, *, fields: Iterable[str]) -> Model | None:
    """The row of the view's model whose primary key is `value`, only when `org_id` owns it.

    Scoped the way the view scopes it: through its `org_filter_path` (a child resource
    such as `agent_definition__org_id`), else the model's own `org`. A row reachable by
    neither, and an id of another organization's row, give None.

    Args:
        fields: The only columns loaded besides the primary key; reading another one
            costs a query of its own.
    """
    model = model_of(view_class)
    if model is None:
        return None
    org_path = org_path_of(view_class, model)
    if org_path is None:
        return None
    try:
        return model._base_manager.filter(pk=value, **{org_path: org_id}).only(*fields).first()
    except (TypeError, ValueError, ValidationError):
        return None


def org_path_of(view_class, model: type[Model]) -> str | None:
    """The lookup path from a row of `model` to its org id, the way the view scopes it: its
    `org_filter_path`, else the model's own `org`; None when the row reaches neither."""
    return getattr(view_class, "org_filter_path", None) or (
        "org_id" if "org" in _field_names(model) else None
    )


def _field_names(model) -> set[str]:
    return {field.name for field in model._meta.concrete_fields}


def _label_of_row(view_class, value, org_id: int, label_fields: tuple[str, ...]) -> str | None:
    """The row's label, read in `org_id` only (see `org_row`), so a label never comes from
    another organization's row."""
    model = model_of(view_class)
    if model is None:
        return None
    field_names = _field_names(model)
    label_field = next((name for name in label_fields if name in field_names), None)
    if label_field is None:
        return None
    row = org_row(view_class, value, org_id, fields=(label_field,))
    label = getattr(row, label_field) if row is not None else None
    return label if isinstance(label, str) and label else None


def model_of(view_class) -> type[Model] | None:
    """The model a view serves: its queryset's, else its serializer's."""
    queryset = getattr(view_class, "queryset", None)
    if queryset is not None:
        return queryset.model
    serializer_meta = getattr(getattr(view_class, "serializer_class", None), "Meta", None)
    return getattr(serializer_meta, "model", None)
