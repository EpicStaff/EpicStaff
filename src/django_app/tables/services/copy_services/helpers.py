import zlib
from collections.abc import Collection

from django.db import connection, models
from django.db.models import Q
from tables.import_export.utils import (
    clean_base_name,
    ensure_unique_identifier,
    ensure_unique_slug,
    slug_base,
)
from tables.models.python_models import PythonCode

#: Distinguishes "the payload omitted secrets" from "the payload sent an empty list".
#: A PATCH that omits secret_ids must leave the declaration alone; one that sends []
#: must clear it.
_UNSET = object()

# Postgres int4 range for the two-key form of pg_advisory_xact_lock.
_INT4_MAX = 2**31


def name_lock_key(org_id: int | None, clean_base: str) -> tuple[int, int]:
    """The two int4 keys of the advisory lock for an (org, name family).

    Callers that take several of these locks sort by this key, so they all take
    them in one order and can't deadlock on each other.
    """
    key2 = zlib.crc32(clean_base.encode("utf-8"))
    if key2 >= _INT4_MAX:
        key2 -= 2**32
    return (org_id if org_id is not None else 0, key2)


def acquire_copy_name_lock(org_id: int | None, clean_base: str) -> None:
    """Serializes concurrent copy-name generation (tool copies, flow copies,
    create-flow-from-version) for the same (org, clean_base) name family via a
    transaction-scoped Postgres advisory lock (`pg_advisory_xact_lock`).

    Why: `ensure_unique_identifier` strips any trailing "#N" suffix before
    computing the next free number, so two DIFFERENT source rows whose names
    both collapse to the same clean_base (e.g. copying "Foo #2" and "Foo #3"
    concurrently) contend for the same generated name even though they don't
    share a source row. A lock on the source row does not cover this — the
    actual contended resource is the (org, clean_base) name space itself.

    Must be called inside an open `transaction.atomic()` block that wraps the
    whole generate-name -> insert step: `pg_advisory_xact_lock` auto-releases
    on commit/rollback of that transaction, no manual unlock needed.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)", list(name_lock_key(org_id, clean_base))
        )


def next_copy_name(
    model: type[models.Model],
    *,
    org_id: int | None,
    base_name: str,
    also_taken: Q | None = None,
    name_field: str = "name",
    org_field: str = "org",
    extra_taken_names: Collection[str] = (),
    case_insensitive_names: bool = False,
    slug_names: bool = False,
    global_names: bool = False,
) -> str:
    """Pick the next free copy name for `base_name` among the org's `model` rows (every org's with `global_names`).

    Takes the per-(org, name family) advisory lock via `acquire_copy_name_lock`, so it
    must be called inside the `transaction.atomic()` block that also inserts the row
    under the returned name; otherwise a concurrent copy can pick the same name.

    `model.objects` decides which rows count as taken: `Graph.objects`
    skips soft-deleted rows, matching the `unique_graph_name_per_org` constraint.

    Args:
        also_taken: Rows outside the org whose names also count as taken. Hybrid
            models need it: their built-in rows (`org IS NULL`) are visible to every
            org, so a copy must not reuse a built-in name.
        name_field: The model's name column (`collection_name` on SourceCollection).
        org_field: The model's organization FK (`organization` on AgentDefinition and Surface).
        extra_taken_names: Names that aren't live yet but will be once the caller's
            transaction ends (other rows a restore brings back), so they count as taken.
        case_insensitive_names: The model's names are unique regardless of case, so
            "report" counts as taking "Report".
        slug_names: The names are identifiers without spaces or "#" (webhook paths):
            a clash gets "-N" (ensure_unique_slug) instead of " #N".
        global_names: The names are unique across all organizations (webhook paths),
            so every org's rows count as taken and the lock isn't per org.
    """
    clean_base = slug_base(base_name) if slug_names else clean_base_name(base_name)
    acquire_copy_name_lock(
        None if global_names else org_id,
        clean_base.lower() if case_insensitive_names else clean_base,
    )
    # Q(pk__isnull=False) is "every row": an empty Q() would vanish from the OR below.
    taken_rows = Q(pk__isnull=False) if global_names else Q(**{f"{org_field}_id": org_id})
    if also_taken is not None:
        taken_rows |= also_taken
    existing_names = list(
        model.objects.filter(taken_rows, **{f"{name_field}__istartswith": clean_base}).values_list(
            name_field, flat=True
        )
    )
    existing_names += list(extra_taken_names)
    if case_insensitive_names:
        # Give every taken name the base's casing (they all start with it, matched
        # case-insensitively), so the exact comparison below treats case variants
        # as the same name and the result keeps the caller's spelling.
        existing_names = [
            clean_base + name[len(clean_base) :]
            if name.lower().startswith(clean_base.lower())
            else name
            for name in existing_names
        ]
    if slug_names:
        max_length = model._meta.get_field(name_field).max_length
        return ensure_unique_slug(
            base_name=base_name, existing_names=existing_names, max_length=max_length
        )
    return ensure_unique_identifier(base_name=base_name, existing_names=existing_names)


def create_python_code(*, python_code_data: dict) -> PythonCode:
    """Create a PythonCode from serializer data, honouring the `secrets` M2M."""
    declared = python_code_data.pop("secrets", None)
    python_code = PythonCode.objects.create(**python_code_data)
    if declared is not None:
        python_code.secrets.set(declared)
    return python_code


def apply_python_code_fields(*, python_code: PythonCode, python_code_data: dict) -> None:
    """Apply serializer data to an existing PythonCode, honouring the M2M."""
    declared = python_code_data.pop("secrets", _UNSET)
    for attr, value in python_code_data.items():
        setattr(python_code, attr, value)
    python_code.save()
    if declared is not _UNSET:
        python_code.secrets.set(declared)


def copy_python_code(python_code: PythonCode) -> PythonCode:
    """Create and return a new PythonCode instance with all fields duplicated."""
    duplicate = PythonCode.objects.create(
        code=python_code.code,
        entrypoint=python_code.entrypoint,
        libraries=python_code.libraries,
        global_kwargs=python_code.global_kwargs,
    )
    # Copy stays inside one org, so the ids remain valid and the duplicate must be
    # runnable. Dropping the declaration would leave a copy that fails validation.
    duplicate.secrets.set(python_code.secrets.all())
    return duplicate


def get_base_node_fields(node) -> dict:
    """Return a dict of the shared BaseNode plain fields (excluding graph and id)."""
    return {
        "input_map": node.input_map,
        "node_name": node.node_name,
        "output_variable_path": node.output_variable_path,
        "metadata": node.metadata,
    }
