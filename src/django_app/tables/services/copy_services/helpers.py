import zlib

from django.db import connection

from tables.models.python_models import PythonCode

#: Distinguishes "the payload omitted secrets" from "the payload sent an empty list".
#: A PATCH that omits secret_ids must leave the declaration alone; one that sends []
#: must clear it.
_UNSET = object()

# Postgres int4 range for the two-key form of pg_advisory_xact_lock.
_INT4_MAX = 2**31


def acquire_copy_name_lock(org_id: int | None, clean_base: str) -> None:
    """Serializes concurrent tool-copy name generation for the same
    (org, clean_base) name family via a transaction-scoped Postgres advisory
    lock (`pg_advisory_xact_lock`).

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
    key1 = org_id if org_id is not None else 0
    key2 = zlib.crc32(clean_base.encode("utf-8"))
    if key2 >= _INT4_MAX:
        key2 -= 2**32
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [key1, key2])


def create_python_code(*, python_code_data: dict) -> PythonCode:
    """Create a PythonCode from serializer data, honouring the `secrets` M2M."""
    declared = python_code_data.pop("secrets", None)
    python_code = PythonCode.objects.create(**python_code_data)
    if declared is not None:
        python_code.secrets.set(declared)
    return python_code


def apply_python_code_fields(
    *, python_code: PythonCode, python_code_data: dict
) -> None:
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
