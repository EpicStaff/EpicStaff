import re
from collections import Counter

from django.conf import settings
from django.db.models import Case, IntegerField, Q, QuerySet, Value, When
from rbac.models import Organization
from rest_framework.exceptions import ValidationError

from tables.import_export.constants import OWNED_SURFACE_ENTRIES_KEY
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.models.label_models import Label


def clean_base_name(base_name: str) -> str:
    """Strips a trailing "#N" (or "# N") suffix from base_name, if present."""
    match = re.match(r"^(.+?)\s*#\s*\d+$", base_name.strip())
    return match.group(1) if match else base_name.strip()


def ensure_unique_identifier(base_name: str, existing_names: list[str]) -> str:
    """
    Creates new unique name from base_name using a trailing "#N" suffix.

    If base_name is already unique it is returned unchanged. Otherwise any
    existing "#N" (or "# N") suffix is stripped to get the base, and the lowest
    free number (starting at 2) is appended, e.g. "My Node" -> "My Node #2",
    "MyAgent #5" -> "MyAgent #2". A freed base name is never reused once a
    collision has occurred -- the result always carries a number, even if the
    plain base name itself is free.
    """
    if base_name not in existing_names:
        return base_name

    clean_base = clean_base_name(base_name)

    existing_numbers = set()
    pattern = re.compile(rf"^{re.escape(clean_base)}\s*#\s*(\d+)$")

    for name in existing_names:
        if name == clean_base:
            existing_numbers.add(1)
        else:
            match = pattern.match(name)
            if match:
                existing_numbers.add(int(match.group(1)))

    i = 2
    while i in existing_numbers:
        i += 1

    return f"{clean_base} #{i}"


def filter_by_name_or_renamed_copy(queryset: QuerySet, name: str | None) -> QuerySet:
    """Narrow `queryset` to rows named `name` or renamed from it by an earlier import.

    `create_entity` renames on a name collision via `ensure_unique_identifier`
    ("surf" -> "surf #2"), so a reuse lookup by the exact exported name never
    finds that copy again and every re-import mints the next number. Rows with
    the exact name sort first, then renamed copies newest first: the copy an
    earlier import of the same file created stays inside the bounded candidate
    window however many older copies exist. The order is deterministic --
    `ImportService` and `import_entity` each call `find_existing` and must agree.
    """
    if name is None:
        return queryset.none()

    renamed_copy_pattern = rf"^{re.escape(clean_base_name(name))}\s*#\s*\d+$"
    return (
        queryset.filter(Q(name=name) | Q(name__regex=renamed_copy_pattern))
        .annotate(
            is_renamed_copy=Case(
                When(name=name, then=Value(0)), default=Value(1), output_field=IntegerField()
            )
        )
        .order_by("is_renamed_copy", "-id")
    )


def create_filters(data: dict) -> tuple[dict, dict]:
    """Get fields from given data and separate filters for isnull fields and actual values"""
    filters, null_filters = {}, {}

    for field, value in data.items():
        if value is None:
            null_filters[f"{field}__isnull"] = True
        else:
            filters[field] = value

    return filters, null_filters


def nest_owned_surface_entries(export_data: dict) -> dict:
    """Return a copy of `export_data` with owned surfaces moved under their agent.

    Each AgentDefinition entry gets `OWNED_SURFACE_ENTRIES_KEY`: the Surface
    entries its `owned_surfaces` ids point at, which are removed from the
    top-level Surface list. Owned surfaces are then matched and created
    together with their agent, so an owned surface is never reused as a shared
    one or as another agent's. Ids without a Surface entry are dropped, and a
    surface listed by several agents goes to the first. Surfaces no agent owns
    stay top-level. The input is not modified; any value of the key in the file
    is overwritten.

    Raises:
        ValidationError: Two AgentDefinition entries share an id. An export never
            writes one twice, and which entry's owned surfaces win would be
            arbitrary.
    """
    agent_entries = export_data.get(EntityType.AGENT_DEFINITION, [])
    if not agent_entries:
        return export_data

    id_counts = Counter(agent_entry.get("id") for agent_entry in agent_entries)
    duplicate_ids = sorted(
        (agent_id for agent_id, count in id_counts.items() if count > 1), key=str
    )
    if duplicate_ids:
        raise ValidationError(
            {"detail": f"Import file lists AgentDefinition ids more than once: {duplicate_ids}."}
        )

    surface_entries_by_id = {
        entry["id"]: entry for entry in export_data.get(EntityType.SURFACE, [])
    }

    nested_agent_entries = []
    for agent_entry in agent_entries:
        owned_entries = [
            surface_entries_by_id.pop(surface_id)
            for surface_id in agent_entry.get("owned_surfaces", [])
            if surface_id in surface_entries_by_id
        ]
        nested_agent_entries.append({**agent_entry, OWNED_SURFACE_ENTRIES_KEY: owned_entries})

    nested_data = {**export_data, EntityType.AGENT_DEFINITION: nested_agent_entries}
    if EntityType.SURFACE in export_data:
        nested_data[EntityType.SURFACE] = list(surface_entries_by_id.values())
    return nested_data


def resolve_import_organization(org_id: int | None) -> Organization | None:
    """
    Resolves the organization an imported entity should be stamped with.

    Prefers the active `org_id` passed into the import. Falls back to the
    default organization when no `org_id` is given (or it does not match an
    existing organization), anchoring on `is_default=True` first since that
    flag survives a rename, then on `name__iexact` against
    `settings.DEFAULT_ORGANIZATION_NAME` for orgs never flagged as default.
    Mirrors `SuperadminBootstrapService._get_or_create_default_org`. Never
    raises `Organization.DoesNotExist`.
    """
    if org_id is not None:
        organization = Organization.objects.filter(id=org_id).first()
        if organization is not None:
            return organization

    organization = Organization.objects.filter(is_default=True).first()
    if organization is not None:
        return organization

    return Organization.objects.filter(name__iexact=settings.DEFAULT_ORGANIZATION_NAME).first()


def import_values(serializer_class, data: dict, field_names) -> dict:
    """Return `data`'s values for `field_names` as the import serializer stores them.

    Each present value runs through its serializer field's run_validation
    (trimming text, coercing numbers), so a reuse lookup compares what
    create_entity would write. Only field-level validation runs, not the
    serializer's validate_<field> or validate(). Absent keys are left out.

    Raises:
        ValidationError: Keyed by field, for every value the field rejects.
    """
    serializer_fields = serializer_class().fields
    values = {}
    errors = {}
    for field_name in field_names:
        if field_name not in data:
            continue
        try:
            values[field_name] = serializer_fields[field_name].run_validation(data[field_name])
        except ValidationError as error:
            errors[field_name] = error.detail
    if errors:
        raise ValidationError(errors)
    return values


def compared_values(model, serializer_class, data: dict, field_names) -> dict:
    """Return the values a reuse lookup compares for `field_names`.

    The file's value as `import_values` stores it; for a key an older file
    lacks, the model default -- also what create_entity stores. Fields without a
    default are left out, since create's value for them is unknown.
    """
    values = import_values(serializer_class, data, field_names)
    for field_name in field_names:
        if field_name in values:
            continue
        field = model._meta.get_field(field_name)
        if field.has_default():
            values[field_name] = field.get_default()
    return values


def attach_tool_labels(instance, id_mapper: IDMapper, label_ids: list) -> None:
    """Attach previously-exported tool labels to a freshly-imported tool instance.

    Same lookup as ``GraphStrategy._set_labels`` (import_export/strategies/graph.py)
    but scoped to ``Label.Scope.TOOL`` instead of ``Scope.FLOW`` — shared between
    ``PythonCodeToolStrategy`` and ``McpToolStrategy`` since both need identical
    logic.
    """
    new_label_ids = [id_mapper.get(EntityType.LABEL, old_id) for old_id in label_ids]
    if new_label_ids:
        instance.labels.add(*Label.objects.filter(id__in=new_label_ids, scope=Label.Scope.TOOL))
