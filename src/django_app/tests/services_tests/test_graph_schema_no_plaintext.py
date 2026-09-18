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
from tables.models.rbac_models import Organization
from tables.services.secrets import secret_service
from tables.services.session_manager_service import SessionManagerService

SENTINEL = "sk-SENTINEL-must-never-be-persisted-9f3a"


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org GraphSchemaLeak")


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
        organization=org,
        name="leak-tester",
        instructions="expose nothing",
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
class TestGraphSchemaNeverHoldsPlaintext:
    def test_sentinel_absent_from_graph_schema_and_present_on_the_wire(
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

        session_id = service.run_session(graph_id=graph.pk, variables={})
        session = Session.objects.get(pk=session_id)

        stored = json.dumps(session.graph_schema)
        assert SENTINEL not in stored, "plaintext key was persisted to graph_schema"
        assert (
            "api_key_secret_id" not in stored
        ), "Secret id leaked into graph_schema; carrier must be exclude=True"

        # The inverse matters just as much: proving the leak closed is worthless
        # if crew no longer receives a usable key.
        wire = "".join(message for _, message in published)
        assert SENTINEL in wire, "crew received no plaintext key"

    def test_original_payload_object_is_not_mutated_by_publishing(
        self, graph_with_secret_backed_llm, monkeypatch
    ):
        graph, secret = graph_with_secret_backed_llm
        service = SessionManagerService()
        monkeypatch.setattr(
            service.redis_service.redis_client, "publish", lambda channel, message: 2
        )

        session = service.create_session(graph_id=graph.pk, variables={})
        session_data = service.create_session_data(session=session)

        service.redis_service.publish_session_data(
            session_data=session_data, org_id=graph.org_id
        )

        assert SENTINEL not in session_data.model_dump_json()


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
            service.run_session(graph_id=graph.pk, variables={})

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
    def test_no_plaintext_reaches_graph_schema(
        self, graph_with_secret_declaring_python_node, monkeypatch
    ):
        graph, secret = graph_with_secret_declaring_python_node
        published = []

        service = SessionManagerService()
        monkeypatch.setattr(
            service.redis_service.redis_client,
            "publish",
            lambda channel, message: published.append((channel, message)) or 2,
        )

        session_id = service.run_session(graph_id=graph.pk, variables={})
        session = Session.objects.get(pk=session_id)

        stored = json.dumps(session.graph_schema)
        assert NODE_SENTINEL not in stored, "declared secret's plaintext persisted"
        assert "secret_names" not in stored, "name carrier must be exclude=True"

        # secrets is a plain (non-excluded) field, so it appears in graph_schema
        # as a key — but it must always be empty there. graph_schema is built
        # from the unresolved original, never from resolve_payload()'s copy, so
        # a non-empty value here would mean resolution leaked into persistence.
        for value in _find_values_by_key(session.graph_schema, "secrets"):
            assert value == {}, "resolved plaintext must never reach graph_schema"

        # The inverse: the sandbox is useless if crew never receives the value.
        wire = "".join(message for _, message in published)
        assert NODE_SENTINEL in wire, "crew received no resolved secret"


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
