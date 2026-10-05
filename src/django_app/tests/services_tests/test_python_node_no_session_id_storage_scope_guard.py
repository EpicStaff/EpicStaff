"""Verifies that the latent `session_id=None` + no-graph-level-storage case
in `ConverterService.convert_python_node_to_pydantic` (hit via subgraph
conversion, which always passes `session_id=None`) is properly guarded against
by `CredentialScopeValidator` before any temporary MinIO credential is minted.

With Commit 8, the issuer and Redis protocol for credential scope are removed;
this test verifies that the converter and validator still enforce the guard.
"""

import pytest

from storage_credentials.exceptions import CredentialScopeValidationError
from storage_credentials.services.scope_validator import CredentialScopeValidator
from tables.models import Graph, PythonCode, PythonNode
from rbac.models import Organization
from tables.services.converter_service import ConverterService


@pytest.fixture
def converter() -> ConverterService:
    return ConverterService()


@pytest.mark.django_db
def test_converter_yields_empty_allowed_paths_without_session_id_or_graph_storage(
    converter,
):
    """`session_id=None` (subgraph conversion path) with no `GraphStorageFile`
    rows attached to the graph must resolve `storage_allowed_paths` to `[]`,
    not `None` -- confirming the converter reaches the latent case described
    in PR #808 rather than short-circuiting somewhere else."""
    org = Organization.objects.create(name="Org Latent")
    graph = Graph.objects.create(name="g-latent", org=org)
    code = PythonCode.objects.create(code="def main(**kw): return kw")
    node = PythonNode.objects.create(graph=graph, python_code=code, use_storage=True)

    data = converter.convert_python_node_to_pydantic(
        node, graph_id=graph.pk, session_id=None
    )

    assert data.python_code.storage_allowed_paths == []
    assert data.python_code.storage_org_prefix == f"org_{org.pk}"
    assert data.python_code.org_id == org.pk


@pytest.mark.django_db
def test_credential_scope_validator_rejects_empty_allowed_paths(converter):
    """The guard: `CredentialScopeValidator.validate()` must reject empty
    `storage_allowed_paths` with a clear error message before any credential
    issuance is attempted. This protects against the latent case where a
    subgraph with `use_storage=True` has no storage paths defined."""
    org = Organization.objects.create(name="Org Latent Validate")
    graph = Graph.objects.create(name="g-latent-validate", org=org)
    code = PythonCode.objects.create(code="def main(**kw): return kw")
    node = PythonNode.objects.create(graph=graph, python_code=code, use_storage=True)

    data = converter.convert_python_node_to_pydantic(
        node, graph_id=graph.pk, session_id=None
    )

    validator = CredentialScopeValidator()
    with pytest.raises(CredentialScopeValidationError) as exc_info:
        validator.validate(
            org_id=data.python_code.org_id,
            storage_org_prefix=data.python_code.storage_org_prefix,
            storage_allowed_paths=data.python_code.storage_allowed_paths,
        )

    error_message = str(exc_info.value)
    assert "storage_allowed_paths is empty" in error_message
    assert "no session_id" in error_message
    assert "GraphStorageFile" in error_message
