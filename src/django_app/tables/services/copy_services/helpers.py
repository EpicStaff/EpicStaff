from tables.models.python_models import PythonCode

#: Distinguishes "the payload omitted secrets" from "the payload sent an empty list".
#: A PATCH that omits secret_ids must leave the declaration alone; one that sends []
#: must clear it.
_UNSET = object()


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
