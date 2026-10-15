"""A panel test run of a node's code is killed at the same limit as a real run.

Invariant: `RunPythonCodeService.run_target` publishes the timeout of the resolved
`PythonCodeData` the node's real run would send, in seconds, as `CodeTaskData.timeout`, so the
sandbox applies it (capped at its maximum) instead of its default. Only the Redis client is
mocked (`redis_client_mock`).
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


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("target_type", "model"),
    [("python_node", PythonNode), ("webhook_trigger_node", WebhookTriggerNode)],
)
def test_test_run_publishes_the_code_timeout(
    org, graph, user, redis_client_mock, settings, target_type, model
):
    settings.MAX_EXECUTION_TIMEOUT_SECONDS = 600
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
    assert published["timeout"] == 42
