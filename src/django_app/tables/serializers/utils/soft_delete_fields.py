from django.db.models import Q
from rbac.scoping.fields import OrgScopedPrimaryKeyRelatedField
from rest_framework import serializers
from tables.models.base_models import SOFT_DELETE_FIELD_NAMES
from tables.services.secrets.reference_guard import secret_reference_guard


class ExcludeSoftDeleteFieldsMixin:
    """Leave the soft-delete state out of a ModelSerializer, whatever its
    `Meta.fields` / `Meta.exclude` say.

    Only DeleteService (and restore) write `active`, `soft_deleted_at` and
    `soft_delete_batch`. Exposed, they let a client or an import file bin a row
    past DeleteService, or break the consistency check (a 500).

    NOTE: DRF builds the validator for a conditional unique constraint
    (`condition=Q(active=True)`) only when `active` is among the fields, so on a
    serializer of such a model (Graph, PythonCodeTool, SourceCollection, McpTool,
    Surface) the name
    clash surfaces as an IntegrityError instead of a 400. Add an explicit
    validator if that serializer writes names without deduplicating them first.
    """

    def get_field_names(self, declared_fields, info):
        field_names = super().get_field_names(declared_fields, info)
        return [name for name in field_names if name not in SOFT_DELETE_FIELD_NAMES]


class KeptLinkPrimaryKeyRelatedField(OrgScopedPrimaryKeyRelatedField):
    """An org-scoped related field that also accepts the binned rows the instance already links to.

    A row in the recycle bin keeps the links to it until it's purged, so a restore brings
    them back working. Saving the linking row unchanged must keep that link, not fail. A new
    link to a binned row is still "Invalid pk", like a missing one. Whatever manager the
    given queryset comes from, the field starts from the model's `all_objects` and narrows
    it to live rows plus the kept ones, so passing `objects` can't quietly undo that. Any
    other filter on the given queryset is dropped too.

    "What the row links to now" comes from the secret reference guard's lookup, so a nested
    serializer resolves through the same hooks (`parent_attribute`,
    `get_current_secret_reference`). Works as a single FK and as the child of `many=True`.
    """

    def __init__(self, *args, queryset=None, **kwargs):
        if queryset is not None:
            queryset = queryset.model.all_objects.all()
        super().__init__(*args, queryset=queryset, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        owner, source = self._owner()
        kept_ids = (
            secret_reference_guard.current_ids(serializer=owner, source=source)
            if owner is not None
            else frozenset()
        )
        return queryset.filter(Q(active=True) | Q(pk__in=kept_ids))

    def _owner(self):
        """The serializer holding this field, and the field's source on it.

        As the child of a `many=True` field the parent is a ManyRelatedField, so the
        serializer and the source are one level up.
        """
        parent = self.parent
        if isinstance(parent, serializers.ManyRelatedField):
            return parent.parent, parent.source
        return parent, self.source
