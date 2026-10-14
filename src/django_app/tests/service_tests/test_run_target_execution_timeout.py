"""A panel test-run of a node's code is killed at the same limit as a real run.

Invariant: `RunPythonCodeService.run_target` publishes the node's own
`execution_timeout`, converted from minutes to the seconds `CodeTaskData.timeout`
expects, so the sandbox applies it (clamped to its ceiling) instead of its default.
Only the Redis client is mocked (`redis_client_mock`).
"""

import json

import pytest

from rbac.models import Organization
from tables.models import Graph, PythonCode
from tables.models.graph_models import PythonNode, WebhookTriggerNode
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


@pytest.fixture
def service():
    return RunPythonCodeService(redis_service=RedisService())


def _python_code() -> PythonCode:
    return PythonCode.objects.create(code="def main(): return 1", entrypoint="main")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("target_type", "model"),
    [("python_node", PythonNode), ("webhook_trigger_node", WebhookTriggerNode)],
)
def test_test_run_publishes_the_node_timeout_in_seconds(
    service, org, graph, user, redis_client_mock, settings, target_type, model
):
    settings.SANDBOX_MAX_EXECUTION_TIMEOUT_MINUTES = 10
    node = model.objects.create(
        graph=graph, node_name="timed", python_code=_python_code(), execution_timeout=3
    )

    service.run_target(
        target_type=target_type,
        target_id=node.pk,
        variables={},
        organization_id=org.id,
        user=user,
    )

    [published] = [json.loads(call.args[1]) for call in redis_client_mock.publish.call_args_list]
    assert published["timeout"] == 180
