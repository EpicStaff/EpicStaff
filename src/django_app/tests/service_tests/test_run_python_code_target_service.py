"""RunPythonCodeService.run_target owns the whole test-run of a code slot: the
org-scoped lookup, the slot's real-run payload, secrets and the publish. Only
the Redis client is mocked (`redis_client_mock`)."""

import json

import pytest

from rbac.models import Organization
from tables.exceptions import CodeRunTargetNotFoundError
from tables.models import Graph, PythonCode, PythonCodeResult, PythonNode
from tables.models.graph_models import ClassificationDecisionTableNode
from tables.services import code_run_targets
from tables.services.code_run_targets import CodeRunTarget
from tables.services.converter_service import ConverterService
from tables.services.redis_service import RedisService
from tables.services.run_python_code_service import RunPythonCodeService

TEST_ONLY_SLOT = "test_only_pre_computation"


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org run target service")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Org run target service other")


@pytest.fixture
def graph(org):
    return Graph.objects.create(name="run-target-service", org=org)


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="run-target-service@example.com", password="StrongPass123!"
    )


@pytest.fixture
def service():
    return RunPythonCodeService(redis_service=RedisService())


@pytest.fixture
def pre_computation_slot(monkeypatch):
    """A registry entry over a nullable slot, the shape a pre-computation target
    has. Test-only: no real entry for this slot exists yet."""
    monkeypatch.setitem(
        code_run_targets.CODE_RUN_TARGETS,
        TEST_ONLY_SLOT,
        CodeRunTarget(
            model=ClassificationDecisionTableNode,
            code_field="pre_python_code",
            build_payload=lambda node, _storage_path: (
                ConverterService().convert_python_code_to_pydantic(node.pre_python_code)
            ),
        ),
    )


def _published_tasks(redis_client_mock):
    return [json.loads(call.args[1]) for call in redis_client_mock.publish.call_args_list]


@pytest.mark.django_db
def test_python_node_with_libraries_uses_the_real_run_venv_name(
    service, org, graph, user, redis_client_mock
):
    python_code = PythonCode.objects.create(
        code="def main(): return 1", entrypoint="main", libraries="httpx"
    )
    node = PythonNode.objects.create(graph=graph, python_code=python_code)
    real_run_venv_name = (
        ConverterService()
        .convert_python_node_to_pydantic(node, graph_id=graph.pk, session_id=1)
        .python_code.venv_name
    )

    service.run_target(
        target_type="python_node",
        target_id=node.pk,
        variables={},
        organization_id=org.id,
        user=user,
    )

    [task] = _published_tasks(redis_client_mock)
    assert task["venv_name"] == real_run_venv_name
    assert task["libraries"] == ["httpx"]


@pytest.mark.django_db
def test_target_in_another_org_raises_not_found(
    service, other_org, graph, user, redis_client_mock
):
    python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    node = PythonNode.objects.create(graph=graph, python_code=python_code)

    with pytest.raises(CodeRunTargetNotFoundError) as raised:
        service.run_target(
            target_type="python_node",
            target_id=node.pk,
            variables={},
            organization_id=other_org.id,
            user=user,
        )

    assert raised.value.target_id == node.pk
    assert not redis_client_mock.publish.call_args_list
    assert not PythonCodeResult.objects.exists()


@pytest.mark.django_db
def test_empty_slot_raises_not_found(
    service, org, graph, user, redis_client_mock, pre_computation_slot
):
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph, node_name="cdt_without_pre", pre_python_code=None
    )

    with pytest.raises(CodeRunTargetNotFoundError):
        service.run_target(
            target_type=TEST_ONLY_SLOT,
            target_id=node.pk,
            variables={},
            organization_id=org.id,
            user=user,
        )

    assert not redis_client_mock.publish.call_args_list
    assert not PythonCodeResult.objects.exists()


@pytest.mark.django_db
def test_filled_slot_runs_and_records_that_slots_code(
    service, org, graph, user, redis_client_mock, pre_computation_slot
):
    pre_code = PythonCode.objects.create(code="def main(): return 'pre'", entrypoint="main")
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph, node_name="cdt_with_pre", pre_python_code=pre_code
    )

    execution_id = service.run_target(
        target_type=TEST_ONLY_SLOT,
        target_id=node.pk,
        variables={},
        organization_id=org.id,
        user=user,
    )

    [task] = _published_tasks(redis_client_mock)
    assert task["code"] == pre_code.code
    assert PythonCodeResult.objects.get(execution_id=execution_id).python_code_id == pre_code.pk
