from django.db.models import Q
from loguru import logger
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

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


class OrgScopedUniqueValidator(UniqueValidator):
    """A ``UniqueValidator`` scoped to the caller's active organization.

    Restores the clean 400 that a global ``unique=True`` field gave automatically,
    for names whose uniqueness moved to a per-org ``UniqueConstraint(org, <field>)``.
    DRF does not auto-validate table-level constraints, so without this a duplicate
    surfaces as a DB IntegrityError (500); this reproduces the old behaviour with a
    single existence query, scoped to the active org.

    Attach to a field's ``validators`` on any per-org-unique field::

        name = serializers.CharField(
            validators=[OrgScopedUniqueValidator(
                queryset=Graph.objects.all(),
                message="A flow with this name already exists.",
            )]
        )

    If the request (and thus the active org) is absent from the serializer context
    the check is skipped and the DB constraint remains the backstop.
    """

    requires_context = True

    def __call__(self, value, serializer_field):
        request = serializer_field.context.get("request")
        if request is None:
            return
        org_id = resolve_active_org_id(request)
        field_name = serializer_field.source_attrs[-1]
        instance = getattr(serializer_field.parent, "instance", None)
        queryset = self.queryset.filter(org_id=org_id, **{field_name: value})
        if instance is not None:
            queryset = queryset.exclude(pk=instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(self.message, code="unique")


class OrgScopedUniqueTogetherValidator:
    """Serializer-level unique-together validator scoped to the active org.

    For a per-org ``UniqueConstraint(org, *fields)`` (or ``unique_together``
    including ``org``) where ``org`` is stamped server-side — DRF cannot add its
    automatic ``UniqueTogetherValidator`` because ``org`` is not a writable field,
    so a duplicate would otherwise surface as a DB IntegrityError (500). Attach on
    the serializer ``Meta.validators``::

        class Meta:
            validators = [OrgScopedUniqueTogetherValidator(
                queryset=PythonCodeToolConfig.objects.all(),
                fields=["tool", "name"],
                message="A config with this name already exists for this tool.",
            )]

    ``fields`` are serializer field names (their model ``source`` is used for the
    lookup). Skipped when the request/active org or the full field set is absent.
    """

    message = "The fields must make a unique set."
    requires_context = True

    def __init__(self, queryset, fields, message=None):
        self.queryset = queryset
        self.fields = list(fields)
        self.message = message or self.message

    def __call__(self, attrs, serializer):
        request = serializer.context.get("request")
        if request is None:
            return
        instance = getattr(serializer, "instance", None)
        filter_kwargs = {"org_id": resolve_active_org_id(request)}
        for field_name in self.fields:
            if field_name in attrs:
                value = attrs[field_name]
            elif instance is not None:
                value = getattr(instance, field_name, None)
            else:
                # partial data without the full set — can't check; DB is backstop
                return
            source = serializer.fields[field_name].source
            filter_kwargs[source] = value
        queryset = self.queryset.filter(**filter_kwargs)
        if instance is not None:
            queryset = queryset.exclude(pk=instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(self.message, code="unique")
