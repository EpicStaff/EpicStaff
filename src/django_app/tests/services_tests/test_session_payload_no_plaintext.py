import json

import pytest

from agents.models import AgentDefinition
from tables.models import (
    Graph,
    LLMConfig,
    LLMModel,
    Provider,
    Secret,
    Session,
)
from tables.models.graph_models import AgentNode, Edge, StartNode
from rbac.models import Organization
from src.shared.models.storage_scope import StorageCredentials
from tables.services.secrets import secret_service
from tables.services.session_manager_service import SessionManagerService
from tables.services.trigger_spec import TriggerSpec

SENTINEL = "sk-SENTINEL-must-never-be-persisted-9f3a"


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org SessionPayloadLeak")


@pytest.fixture
def graph_with_secret_backed_llm(org):
    """Minimal runnable graph whose agent's LLM config holds SENTINEL."""
    provider, _ = Provider.objects.get_or_create(name="openai")
    model = LLMModel.objects.create(name="gpt-4o-leak-test", llm_provider=provider)
    secret = secret_service.create(text=SENTINEL, org=org, name="leak-test-key")
    llm_config = LLMConfig.objects.create(
        custom_name="leak-test-cfg", model=model, org=org, api_key_secret=secret
    )

    agent_definition = AgentDefinition.objects.create(
        org=org,
        name="leak-tester",
        instruction_list=[{"name": "Instruction_1.md", "content": "expose nothing"}],
        llm_config=llm_config,
    )

    graph = Graph.objects.create(name="leak-test-graph", org=org)
    # StartNode.node_name is a fixed "__start__" property, not a column.
    start = StartNode.objects.create(graph=graph, variables={"variables": {}})
    agent_node = AgentNode.objects.create(
        graph=graph, agent_definition=agent_definition, node_name="agent_node"
    )
    # Without an edge off the start node, conversion raises
    # GraphEntryPointException before any payload is built.
    Edge.objects.create(graph=graph, start_node_id=start.pk, end_node_id=agent_node.pk)
    return graph, secret


@pytest.mark.django_db
class TestSessionPayloadSecrets:
    def test_wire_carries_the_plaintext_key_but_no_secret_id(
        self, graph_with_secret_backed_llm, monkeypatch
    ):
        graph, secret = graph_with_secret_backed_llm
        published = []

        service = SessionManagerService()
        monkeypatch.setattr(
            service.redis_service.redis_client,
            "publish",
            lambda channel, message: published.append((channel, message)) or 2,
        )

        service.run_session(graph_id=graph.pk, variables={}, trigger=TriggerSpec.manual())

        wire = "".join(message for _, message in published)
        assert SENTINEL in wire, "crew received no plaintext key"
        assert (
            "api_key_secret_id" not in wire
        ), "Secret id leaked into the Redis payload; carrier must be exclude=True"
        assert SENTINEL not in _stored_sessions(graph), "plaintext key was persisted"

    def test_original_payload_object_is_not_mutated_by_publishing(
        self, graph_with_secret_backed_llm, monkeypatch
    ):
        graph, secret = graph_with_secret_backed_llm
        service = SessionManagerService()
        monkeypatch.setattr(
            service.redis_service.redis_client, "publish", lambda channel, message: 2
        )

        start_node = StartNode.objects.get(graph=graph)
        session = service.create_session(
            graph=graph, start_node=start_node, variables={}, trigger=TriggerSpec.manual()
        )
        session_data = service.create_session_data(session=session, start_node=start_node)

        service.redis_service.publish_session_data(
            session_data=session_data, org_id=graph.org_id
        )

        assert SENTINEL not in session_data.model_dump_json()

    def test_run_session_forwards_issued_credentials_to_the_wire(
        self, graph_with_secret_backed_llm, monkeypatch
    ):
        from unittest.mock import patch

        graph, _ = graph_with_secret_backed_llm
        published = []
        service = SessionManagerService()
        monkeypatch.setattr(
            service.redis_service.redis_client,
            "publish",
            lambda channel, message: published.append(message) or 2,
        )

        with patch(
            "storage_credentials.services.session_credential_service."
            "session_credential_service.issue_for_session",
            return_value=StorageCredentials(
                access_key="AK-run-session", secret_key="SK-run-session"
            ),
        ):
            service.run_session(
                graph_id=graph.pk, variables={}, trigger=TriggerSpec.manual()
            )

        assert json.loads(published[0])["storage_credentials"] == {
            "access_key": "AK-run-session",
            "secret_key": "SK-run-session",
        }
        assert "SK-run-session" not in _stored_sessions(graph), "storage secret key was persisted"

    def test_storage_credentials_live_only_on_the_published_copy(
        self, graph_with_secret_backed_llm, monkeypatch
    ):
        graph, _ = graph_with_secret_backed_llm
        published = []
        service = SessionManagerService()
        monkeypatch.setattr(
            service.redis_service.redis_client,
            "publish",
            lambda channel, message: published.append(message) or 2,
        )

        start_node = StartNode.objects.get(graph=graph)
        session = service.create_session(
            graph=graph, start_node=start_node, variables={}, trigger=TriggerSpec.manual()
        )
        session_data = service.create_session_data(session=session, start_node=start_node)
        credentials = StorageCredentials(
            access_key="AK-published-only", secret_key="SK-published-only"
        )

        service.redis_service.publish_session_data(
            session_data=session_data,
            org_id=graph.org_id,
            storage_credentials=credentials,
        )

        assert session_data.storage_credentials is None, (
            "publish_session_data mutated the caller's object; the credentials "
            "must exist only on the published copy"
        )
        payload = json.loads(published[0])
        assert payload["storage_credentials"] == {
            "access_key": "AK-published-only",
            "secret_key": "SK-published-only",
        }

    def test_published_copy_carries_no_credentials_when_none_were_issued(
        self, graph_with_secret_backed_llm, monkeypatch
    ):
        graph, _ = graph_with_secret_backed_llm
        published = []
        service = SessionManagerService()
        monkeypatch.setattr(
            service.redis_service.redis_client,
            "publish",
            lambda channel, message: published.append(message) or 2,
        )

        start_node = StartNode.objects.get(graph=graph)
        session = service.create_session(
            graph=graph, start_node=start_node, variables={}, trigger=TriggerSpec.manual()
        )
        session_data = service.create_session_data(session=session, start_node=start_node)

        service.redis_service.publish_session_data(
            session_data=session_data, org_id=graph.org_id
        )

        assert json.loads(published[0])["storage_credentials"] is None


@pytest.mark.django_db
class TestUnresolvableSecretFailsTheSession:
    def test_unresolvable_secret_marks_session_error_and_publishes_nothing(
        self, graph_with_secret_backed_llm, monkeypatch
    ):
        graph, secret = graph_with_secret_backed_llm
        # Corrupt the stored ciphertext rather than dangling the FK: a dangling
        # FK id is impossible to write, Postgres rejects it with a
        # ForeignKeyViolation. An unopenable value reaches the same
        # SecretResolutionError path.
        Secret.objects.filter(pk=secret.pk).update(value="not-valid-fernet")

        published = []
        service = SessionManagerService()
        monkeypatch.setattr(
            service.redis_service.redis_client,
            "publish",
            lambda channel, message: published.append(message) or 2,
        )

        with pytest.raises(Exception):
            service.run_session(
                graph_id=graph.pk, variables={}, trigger=TriggerSpec.manual()
            )

        session = Session.objects.filter(graph_id=graph.pk).latest("pk")
        assert session.status == Session.SessionStatus.ERROR
        assert "reason" in session.status_data
        assert not published, "a session with an unresolvable secret was published"


NODE_SENTINEL = "sk-NODE-SENTINEL-must-never-be-persisted-2c8e"


@pytest.fixture
def graph_with_secret_declaring_python_node(org):
    """A runnable graph whose Python node asks for a Secret holding NODE_SENTINEL.

    The declaration is the get_secret("...") literal in the code — there is no
    request field and no relation to set, which is why this works identically for
    a Python node, a decision-table pre/post block and a custom tool.
    """
    from tables.models import PythonCode
    from tables.models.graph_models import PythonNode

    secret = secret_service.create(
        text=NODE_SENTINEL, org=org, name="node-decl-leak-test"
    )
    python_code = PythonCode.objects.create(
        code=(
            "def main(**kwargs):\n"
            '    return get_secret("node-decl-leak-test") is not None\n'
        ),
        entrypoint="main",
    )
    # The declaration is the M2M now, not the literal in the code. Without this the
    # node would fail session-start validation instead of publishing.
    python_code.secrets.set([secret])

    graph = Graph.objects.create(name="node-decl-graph", org=org)
    start = StartNode.objects.create(graph=graph, variables={"variables": {}})
    node = PythonNode.objects.create(
        graph=graph, python_code=python_code, node_name="py_node"
    )
    Edge.objects.create(graph=graph, start_node_id=start.pk, end_node_id=node.pk)
    return graph, secret


@pytest.mark.django_db
class TestDeclaredNodeSecretsNeverPersist:
    def test_run_session_publishes_the_secret_and_stores_none_of_it(
        self, graph_with_secret_declaring_python_node, monkeypatch
    ):
        graph, secret = graph_with_secret_declaring_python_node
        published = []
        service = SessionManagerService()
        monkeypatch.setattr(
            service.redis_service.redis_client,
            "publish",
            lambda channel, message: published.append(message) or 2,
        )

        service.run_session(graph_id=graph.pk, variables={}, trigger=TriggerSpec.manual())

        assert NODE_SENTINEL in "".join(published), "crew received no resolved secret"
        assert NODE_SENTINEL not in _stored_sessions(graph), "declared secret's plaintext persisted"

    def test_plaintext_reaches_only_the_published_copy(
        self, graph_with_secret_declaring_python_node, monkeypatch
    ):
        graph, secret = graph_with_secret_declaring_python_node
        published = []
        service = SessionManagerService()
        monkeypatch.setattr(
            service.redis_service.redis_client,
            "publish",
            lambda channel, message: published.append(message) or 2,
        )
        start_node = StartNode.objects.get(graph=graph)
        session = service.create_session(
            graph=graph, start_node=start_node, variables={}, trigger=TriggerSpec.manual()
        )
        session_data = service.create_session_data(session=session, start_node=start_node)

        service.redis_service.publish_session_data(
            session_data=session_data, org_id=graph.org_id
        )

        wire = published[0]
        assert NODE_SENTINEL in wire, "crew received no resolved secret"
        assert "secret_names" not in wire, "name carrier must be exclude=True"

        # `secrets` is a plain field, so the caller's dump has the key, but resolution
        # happens on a copy: a non-empty value here means it ran in place.
        caller_dump = json.loads(session_data.model_dump_json())
        assert NODE_SENTINEL not in json.dumps(caller_dump)
        caller_secrets = list(_find_values_by_key(caller_dump, "secrets"))
        assert caller_secrets, "the python node's secrets field is missing from the dump"
        assert all(value == {} for value in caller_secrets)


def _stored_sessions(graph) -> str:
    """Every column of every session row of the graph, as one string."""
    return json.dumps(list(Session.objects.filter(graph=graph).values()), default=str)


def _find_values_by_key(node, key):
    """Recursively collect every value stored under `key` anywhere in `node`."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                yield v
            yield from _find_values_by_key(v, key)
    elif isinstance(node, list):
        for item in node:
            yield from _find_values_by_key(item, key)
