"""A panel test run of a node's code is killed at the same limit as a real run.

Invariant: `RunPythonCodeService.run_target` publishes the timeout of the resolved
`PythonCodeData` the node's real run would send, in seconds, as `CodeTaskData.execution_timeout`,
so the sandbox applies it (capped at its maximum) instead of its default. A test run of a python
code tool's code publishes the code's own timeout too, as a real tool run does. Only the Redis
client is mocked (`redis_client_mock`).
"""

import dataclasses
import json

import pytest

from rbac.models import Organization
from tables.models import Graph, PythonCode, PythonCodeTool
from tables.models.graph_models import PythonNode, WebhookTriggerNode
from tables.services.code_run_targets import CODE_RUN_TARGETS
from tables.services.redis_service import RedisService
from tables.services.run_python_code_service import RunPythonCodeService


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org run target execution timeout")


@pytest.fixture
def graph(org):
    return Graph.objects.create(name="run-target-execution-timeout", org=org)


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="run-target-execution-timeout@example.com", password="StrongPass123!"
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("target_type", "model"),
    [("python_node", PythonNode), ("webhook_trigger_node", WebhookTriggerNode)],
)
def test_test_run_publishes_the_code_timeout(
    org, graph, user, redis_client_mock, target_type, model
):
    python_code = PythonCode.objects.create(code="def main(): return 1", execution_timeout=42)
    node = model.objects.create(graph=graph, node_name="timed", python_code=python_code)

    RunPythonCodeService(redis_service=RedisService()).run_target(
        target_type=target_type,
        target_id=node.pk,
        variables={},
        organization_id=org.id,
        user=user,
    )

    [published] = [json.loads(call.args[1]) for call in redis_client_mock.publish.call_args_list]
    assert published["execution_timeout"] == 42


@pytest.mark.django_db
def test_test_run_publishes_the_timeout_of_the_resolved_payload(
    org, graph, user, redis_client_mock, monkeypatch
):
    real_target = CODE_RUN_TARGETS["python_node"]

    def build_payload_with_other_timeout(owner, storage_path):
        payload = real_target.build_payload(owner, storage_path)
        return payload.model_copy(update={"execution_timeout": 77})

    monkeypatch.setitem(
        CODE_RUN_TARGETS,
        "python_node",
        dataclasses.replace(real_target, build_payload=build_payload_with_other_timeout),
    )
    python_code = PythonCode.objects.create(code="def main(): return 1", execution_timeout=42)
    node = PythonNode.objects.create(graph=graph, node_name="timed", python_code=python_code)

    RunPythonCodeService(redis_service=RedisService()).run_target(
        target_type="python_node",
        target_id=node.pk,
        variables={},
        organization_id=org.id,
        user=user,
    )

    [published] = [json.loads(call.args[1]) for call in redis_client_mock.publish.call_args_list]
    assert published["execution_timeout"] == 77


@pytest.mark.django_db
def test_tool_code_test_run_publishes_the_code_timeout(org, user, redis_client_mock):
    python_code = PythonCode.objects.create(code="def main(): return 1", execution_timeout=42)
    PythonCodeTool.objects.create(
        name="timeout-tool", description="tool", org=org, python_code=python_code
    )

    RunPythonCodeService(redis_service=RedisService()).run_code(
        python_code_id=python_code.pk,
        varaibles={},
        organization_id=org.id,
        user=user,
    )

    [published] = [json.loads(call.args[1]) for call in redis_client_mock.publish.call_args_list]
    assert published["execution_timeout"] == 42
