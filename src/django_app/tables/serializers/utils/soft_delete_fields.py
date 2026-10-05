from tables.models.base_models import SOFT_DELETE_FIELD_NAMES


class ExcludeSoftDeleteFieldsMixin:
    """Leave the soft-delete state out of a ModelSerializer, whatever its
    `Meta.fields` / `Meta.exclude` say.

    Only DeleteService (and restore) write `active`, `soft_deleted_at` and
    `soft_delete_batch`. Exposed, they let a client or an import file bin a row
    past DeleteService, or break the consistency check (a 500).

    NOTE: DRF builds the validator for a conditional unique constraint
    (`condition=Q(active=True)`) only when `active` is among the fields, so on a
    serializer of such a model (Graph, PythonCodeTool, SourceCollection) the name
    clash surfaces as an IntegrityError instead of a 400. Add an explicit
    validator if that serializer writes names without deduplicating them first.
    """

    def get_field_names(self, declared_fields, info):
        field_names = super().get_field_names(declared_fields, info)
        return [name for name in field_names if name not in SOFT_DELETE_FIELD_NAMES]
