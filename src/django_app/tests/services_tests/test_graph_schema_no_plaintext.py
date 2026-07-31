import json

import pytest

from tables.models import (
    Agent,
    Crew,
    Graph,
    LLMConfig,
    LLMModel,
    Provider,
    Secret,
    Session,
    Task,
)
from tables.models.graph_models import CrewNode, Edge, StartNode
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

    agent = Agent.objects.create(
        role="leak-tester",
        goal="expose nothing",
        backstory="none",
        llm_config=llm_config,
        org=org,
    )
    crew = Crew.objects.create(name="leak-test-crew", org=org)
    crew.agents.set([agent])
    # converter_service asserts a crew has at least one task before building
    # its payload, so the graph is not convertible without this.
    Task.objects.create(
        crew=crew,
        agent=agent,
        name="leak-test-task",
        instructions="do nothing",
        expected_output="nothing",
        order=1,
    )

    graph = Graph.objects.create(name="leak-test-graph", org=org)
    # StartNode.node_name is a fixed "__start__" property, not a column.
    start = StartNode.objects.create(graph=graph, variables={"variables": {}})
    crew_node = CrewNode.objects.create(graph=graph, crew=crew, node_name="crew_node")
    # Without an edge off the start node, conversion raises
    # GraphEntryPointException before any payload is built.
    Edge.objects.create(graph=graph, start_node_id=start.pk, end_node_id=crew_node.pk)
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

        service.redis_service.publish_session_data(session_data=session_data)

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
