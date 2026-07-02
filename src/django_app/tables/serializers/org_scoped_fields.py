from django.db.models import Q
from loguru import logger
from rest_framework import serializers

from tables.services.rbac.org_context_service import OrgContextService


def resolve_active_org_id(request) -> int:
    """Active org id for the request, resolved from the X-Organization-Id header
    and cached on the request under `_rbac_active_org_id` (the same key
    OrgScopedViewSetMixin uses), so it resolves at most once per request."""
    org_id = getattr(request, "_rbac_active_org_id", None)
    if org_id is None:
        org_id = OrgContextService().resolve(request=request)
        request._rbac_active_org_id = org_id
    return org_id


def org_visible_q(model, org_id):
    """The visibility filter (`Q`) for `model` under `org_id`, or ``None`` when the
    model is global (has no `org` field). Single source of truth for the scoping
    rules, shared by :func:`org_visible_queryset` and
    :class:`OrgVisiblePrimaryKeyRelatedField`:

    - **hybrid** (`built_in` flag, e.g. PythonCodeTool): built-ins + own-org rows;
    - **hybrid** (`is_custom` flag, e.g. *Model): built-ins (is_custom=False) + own-org;
    - **strict** (has `org`, no flag, e.g. McpTool / PythonCodeToolConfig / configs):
      own-org rows only;
    - **global** (no `org` field, e.g. the deprecated ToolConfig): ``None`` (no filter).
    """
    field_names = {f.name for f in model._meta.get_fields()}
    if "org" not in field_names:
        return None
    if "built_in" in field_names:
        return Q(built_in=True) | Q(org_id=org_id)
    if "is_custom" in field_names:
        return Q(is_custom=False) | Q(org_id=org_id)
    return Q(org_id=org_id)


def org_visible_queryset(model, org_id):
    """Rows of `model` visible to `org_id`, applying the same scoping rules as the
    org viewset mixins — so non-FK reference resolution (e.g. the string-encoded
    `tool_ids`) honours org isolation identically. See :func:`org_visible_q`."""
    q = org_visible_q(model, org_id)
    return model.objects.filter(q) if q is not None else model.objects.all()


def _warn_missing_request(field) -> None:
    """Log a warning when an org-scoped related field is resolved without a request
    in context — a programming error (the serializer was built without
    ``context={"request": request}``) that makes the field deny all pks."""
    parent_name = (
        type(field.parent).__name__
        if field.parent is not None
        else "<unbound serializer>"
    )
    logger.warning(
        f"{type(field).__name__} '{field.field_name}' on {parent_name} was resolved "
        f"without a request in the serializer context; denying all pks because org "
        f"scope cannot be applied. Construct the serializer with the request in its "
        f"context."
    )


class OrgScopedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """A ``PrimaryKeyRelatedField`` narrowed to the caller's active organization.

    Use for **write** fields that reference an org-scoped model (FK or M2M) so a
    pk belonging to another org is rejected exactly like a non-existent pk
    ("Invalid pk … object does not exist") — existence in another org is never
    revealed, consistent with the 404-on-cross-org policy.

    ``org_lookup`` is the ORM path from the related model to the org id:
    - default ``"org_id"`` for models that own an ``org`` FK directly (e.g. Agent);
    - e.g. ``"crew__org_id"`` for a model scoped via a parent.

    Requires the serializer context to carry ``request`` (the active org is read
    from the ``X-Organization-Id`` header via ``OrgContextService``). With no
    request in context the field cannot apply org scoping, so it **denies all
    pks** (returns an empty queryset) and logs a warning — a missing request on
    a write path is a programming error (the serializer was built without
    ``context={"request": request}``), and denying is fail-safe rather than
    leaking cross-org rows.
    """

    org_lookup = "org_id"

    def __init__(self, *args, org_lookup=None, **kwargs):
        if org_lookup is not None:
            self.org_lookup = org_lookup
        super().__init__(*args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        request = self.context.get("request")
        if request is None:
            _warn_missing_request(self)
            return queryset.none()
        return queryset.filter(**{self.org_lookup: resolve_active_org_id(request)})


class OrgVisiblePrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """A ``PrimaryKeyRelatedField`` for **hybrid** org-scoped targets — models that
    are either shared built-ins (visible to every org) or an org's own custom rows
    (e.g. LLMModel / EmbeddingModel / Realtime*Model via ``is_custom``,
    PythonCodeTool via ``built_in``).

    Applies the :func:`org_visible_q` rule (built-ins OR active-org rows) so a pk
    belonging to another org's custom rows is rejected exactly like a non-existent
    pk, while shared built-ins stay referenceable. Use this — not
    ``OrgScopedPrimaryKeyRelatedField`` — for FKs whose target is a hybrid model,
    otherwise shared built-ins would wrongly become unreferenceable.

    Same no-request deny+warn fallback as ``OrgScopedPrimaryKeyRelatedField``.
    """

    def get_queryset(self):
        queryset = super().get_queryset()
        request = self.context.get("request")
        if request is None:
            _warn_missing_request(self)
            return queryset.none()
        q = org_visible_q(queryset.model, resolve_active_org_id(request))
        return queryset.filter(q) if q is not None else queryset
