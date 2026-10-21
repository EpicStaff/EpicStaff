from django.db.models import Q
from rbac.scoping.fields import OrgScopedPrimaryKeyRelatedField
from rest_framework import serializers
from tables.models.base_models import SOFT_DELETE_FIELD_NAMES, without_internal_rows
from tables.serializers.utils.persisted_value import PersistedValueMixin
from tables.services.secrets.linked_ids import linked_ids


class ExcludeSoftDeleteFieldsMixin:
    """Leave the soft-delete state out of a ModelSerializer, whatever its
    `Meta.fields` / `Meta.exclude` say.

    Only DeleteService (and restore) write `active`, `soft_deleted_at` and
    `soft_delete_batch`. Exposed, they let a client or an import file bin a row
    past DeleteService, or break the consistency check (a 500).

    NOTE: DRF (3.16) builds the validator for a conditional unique constraint over
    several fields, such as a name unique per org among live rows
    (`fields=("org", "name"), condition=Q(active=True)`), only when `active` is
    among the serializer's fields. With this mixin it never is, so such a clash
    surfaces as an IntegrityError instead of a 400: add an explicit validator if
    the serializer writes names without deduplicating them first. A conditional
    constraint on one field (TwilioChannel's `phone_number`) is unaffected: DRF
    always gives that field a UniqueValidator filtered by the condition.
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
    other filter on the given queryset is dropped too, but the model's `internal_rows`
    (Secret's system rows) are always left out, kept or not.

    "What the row links to now" is asked of the serializer holding the field, through
    `PersistedValueMixin.persisted_value` -- the same answer the secret reference guard
    compares against -- so that serializer must mix it in. Works as a single FK and as
    the child of `many=True`.
    """

    def __init__(self, *args, queryset=None, **kwargs):
        if queryset is not None:
            queryset = without_internal_rows(queryset.model.all_objects.all())
        super().__init__(*args, queryset=queryset, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        owner, source = self._owner()
        kept_ids = linked_ids(owner.persisted_value(source)) if owner is not None else frozenset()
        return queryset.filter(Q(active=True) | Q(pk__in=kept_ids))

    def _owner(self):
        """The serializer holding this field, and the field's source on it.

        As the child of a `many=True` field the parent is a ManyRelatedField, so the
        serializer and the source are one level up.
        """
        parent = self.parent
        if isinstance(parent, serializers.ManyRelatedField):
            owner, source = parent.parent, parent.source
        else:
            owner, source = parent, self.source
        if owner is not None and not isinstance(owner, PersistedValueMixin):
            raise TypeError(
                f"{type(owner).__name__} declares a KeptLinkPrimaryKeyRelatedField but does "
                "not mix in PersistedValueMixin, so the link it already holds is unknown."
            )
        return owner, source
