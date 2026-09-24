"""Verifies the latent `session_id=None` + no-graph-level-storage-items case
in `ConverterService.convert_python_node_to_pydantic` (hit via
`SessionManagerService._build_graph_data` for subgraph conversion, which
always passes `session_id=None`) is caught by `CredentialScopeValidator`
before any temporary MinIO credential is minted.

This is a verification test, not a logic change: it traces the real
end-to-end path -- converter -> `CodeTaskData` -> `publish_credential_scope`
-> the issuer's `CredentialScopeValidator.validate()` -- confirming each
echelon behaves as PR #808's review concluded, with no new guard added here.
"""

import json

import fakeredis
import pytest

from src.shared.models import CodeTaskData
from src.shared.storage_credentials import publish_credential_scope
from storage_credentials.exceptions import CredentialScopeValidationError
from storage_credentials.redis import keys
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
    in the PR #808 review rather than short-circuiting somewhere else."""
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
def test_publish_credential_scope_does_not_guard_against_empty_allowed_paths(
    converter,
):
    """`publish_credential_scope` is the first echelon of defense and only
    guards `org_id`/`storage_org_prefix` (`_build_scope_payload`) -- it has
    no opinion on `storage_allowed_paths` being empty, so the empty list from
    the converter is published to Redis as-is. The real guard lives further
    downstream, at credential-issue time (next test) -- not here."""
    org = Organization.objects.create(name="Org Latent Publish")
    graph = Graph.objects.create(name="g-latent-publish", org=org)
    code = PythonCode.objects.create(code="def main(**kw): return kw")
    node = PythonNode.objects.create(graph=graph, python_code=code, use_storage=True)

    data = converter.convert_python_node_to_pydantic(
        node, graph_id=graph.pk, session_id=None
    )

    execution_id = "exec-latent-1"
    code_task_data = CodeTaskData(
        venv_name="venv_1",
        libraries=[],
        code=code.code,
        entrypoint="main",
        execution_id=execution_id,
        use_storage=True,
        storage_allowed_paths=data.python_code.storage_allowed_paths,
        storage_org_prefix=data.python_code.storage_org_prefix,
        org_id=data.python_code.org_id,
    )

    redis_client = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    publish_credential_scope(redis_client, code_task_data)

    raw_scope = redis_client.get(keys.scope_key(execution_id))
    assert raw_scope is not None, (
        "publish_credential_scope silently dropped the scope instead of "
        "publishing it -- if this assertion ever fails, the guard has moved "
        "earlier and this test (and the next one) need updating."
    )

    published_scope = json.loads(raw_scope)
    assert published_scope["storage_allowed_paths"] == []
    assert published_scope["org_id"] == org.pk
    assert published_scope["storage_org_prefix"] == f"org_{org.pk}"


@pytest.mark.django_db
def test_credential_scope_validator_rejects_the_published_empty_scope(converter):
    """The actual guard: by the time the issuer reads the scope back
    (`GETDEL`) and calls `CredentialScopeValidator.validate()` -- exercised
    directly here rather than through the async Redis Stream consumer -- an
    empty `storage_allowed_paths` must raise `CredentialScopeValidationError`
    before `TemporaryCredentialService.issue()` ever calls MinIO."""
    org = Organization.objects.create(name="Org Latent Validate")
    graph = Graph.objects.create(name="g-latent-validate", org=org)
    code = PythonCode.objects.create(code="def main(**kw): return kw")
    node = PythonNode.objects.create(graph=graph, python_code=code, use_storage=True)

    data = converter.convert_python_node_to_pydantic(
        node, graph_id=graph.pk, session_id=None
    )

    execution_id = "exec-latent-2"
    code_task_data = CodeTaskData(
        venv_name="venv_1",
        libraries=[],
        code=code.code,
        entrypoint="main",
        execution_id=execution_id,
        use_storage=True,
        storage_allowed_paths=data.python_code.storage_allowed_paths,
        storage_org_prefix=data.python_code.storage_org_prefix,
        org_id=data.python_code.org_id,
    )

    redis_client = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    publish_credential_scope(redis_client, code_task_data)
    published_scope = json.loads(redis_client.getdel(keys.scope_key(execution_id)))

    validator = CredentialScopeValidator()
    with pytest.raises(CredentialScopeValidationError) as exc_info:
        validator.validate(
            org_id=published_scope["org_id"],
            storage_org_prefix=published_scope["storage_org_prefix"],
            storage_allowed_paths=published_scope.get("storage_allowed_paths"),
        )

    error_message = str(exc_info.value)
    assert "storage_allowed_paths is empty" in error_message
    assert "no session_id" in error_message
    assert "GraphStorageFile" in error_message
