"""Session-start validation: the boundary that actually holds.

Save-time validation is bypassable — import, copy services, upload_tools and
direct DB writes all reach PythonCode without passing through
PythonCodeSerializer — so these tests write the models directly, exactly as those
paths do.
"""

import pytest

from tables.models import PythonCode
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    ConditionalEdge,
    Graph,
    PythonNode,
    WebhookTriggerNode,
)
from tables.models.rbac_models import Organization
from tables.services.secrets import secret_service
from tables.services.secrets.declaration_validator import (
    secret_declaration_validator,
)

DECLARING_CODE = 'def main(**kwargs):\n    return get_secret("VAL_KEY")\n'


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org DeclValidator")


@pytest.fixture
def secret(org):
    return secret_service.create(text="sk-val", org=org, name="VAL_KEY")


@pytest.fixture
def graph(org):
    return Graph.objects.create(name="Validator flow", org=org)


@pytest.mark.django_db
class TestViolations:
    def test_undeclared_secret_in_a_python_node_is_reported(self, graph, secret):
        PythonNode.objects.create(
            graph=graph,
            node_name="charge_card",
            python_code=PythonCode.objects.create(code=DECLARING_CODE),
        )

        violations = secret_declaration_validator.violations(graph_id=graph.pk)

        assert len(violations) == 1
        assert violations[0].node_name == "charge_card"
        assert violations[0].undeclared == ["VAL_KEY"]
        assert violations[0].declared == []

    def test_a_declared_secret_is_not_a_violation(self, graph, secret):
        python_code = PythonCode.objects.create(code=DECLARING_CODE)
        python_code.secrets.set([secret])
        PythonNode.objects.create(
            graph=graph, node_name="declared", python_code=python_code
        )

        assert secret_declaration_validator.violations(graph_id=graph.pk) == []

    def test_declared_but_unused_is_not_a_violation(self, graph, secret):
        python_code = PythonCode.objects.create(
            code="def main(**kwargs):\n    return 1\n"
        )
        python_code.secrets.set([secret])
        PythonNode.objects.create(
            graph=graph, node_name="unused", python_code=python_code
        )

        assert secret_declaration_validator.violations(graph_id=graph.pk) == []

    def test_every_violation_is_reported_not_just_the_first(self, graph):
        for node_name in ("first", "second"):
            PythonNode.objects.create(
                graph=graph,
                node_name=node_name,
                python_code=PythonCode.objects.create(code=DECLARING_CODE),
            )

        violations = secret_declaration_validator.violations(graph_id=graph.pk)

        assert sorted(violation.node_name for violation in violations) == [
            "first",
            "second",
        ]

    def test_a_name_only_in_a_comment_is_not_a_violation(self, graph):
        PythonNode.objects.create(
            graph=graph,
            node_name="commented",
            python_code=PythonCode.objects.create(
                code='def main(**kwargs):\n    # get_secret("VAL_KEY")\n    return 1\n'
            ),
        )

        assert secret_declaration_validator.violations(graph_id=graph.pk) == []

    def test_unparseable_code_is_not_a_violation(self, graph):
        """Code that cannot parse cannot run, so blocking the session on it would
        stop a flow over a node the user has not finished writing."""
        PythonNode.objects.create(
            graph=graph,
            node_name="broken",
            python_code=PythonCode.objects.create(
                code='def main(:\n    get_secret("VAL_KEY")\n'
            ),
        )

        assert secret_declaration_validator.violations(graph_id=graph.pk) == []

    def test_a_webhook_trigger_node_is_checked(self, graph):
        WebhookTriggerNode.objects.create(
            graph=graph,
            node_name="on_hook",
            python_code=PythonCode.objects.create(code=DECLARING_CODE),
        )

        violations = secret_declaration_validator.violations(graph_id=graph.pk)

        assert [violation.node_name for violation in violations] == ["on_hook"]

    def test_both_cdt_blocks_are_checked(self, graph):
        ClassificationDecisionTableNode.objects.create(
            graph=graph,
            node_name="classify",
            pre_python_code=PythonCode.objects.create(code=DECLARING_CODE),
            post_python_code=PythonCode.objects.create(code=DECLARING_CODE),
        )

        violations = secret_declaration_validator.violations(graph_id=graph.pk)

        # Two blocks, two PythonCode rows — reported once each.
        assert len(violations) == 2

    def test_a_conditional_edge_is_checked(self, graph):
        ConditionalEdge.objects.create(
            graph=graph,
            source_node_id=None,
            python_code=PythonCode.objects.create(code=DECLARING_CODE),
        )

        violations = secret_declaration_validator.violations(graph_id=graph.pk)

        assert len(violations) == 1
        assert violations[0].undeclared == ["VAL_KEY"]

    def test_another_graphs_node_is_not_reported(self, org, graph):
        other_graph = Graph.objects.create(name="Other validator flow", org=org)
        PythonNode.objects.create(
            graph=other_graph,
            node_name="elsewhere",
            python_code=PythonCode.objects.create(code=DECLARING_CODE),
        )

        assert secret_declaration_validator.violations(graph_id=graph.pk) == []


from tables.models import Session
from tables.models.graph_models import Edge, StartNode
from tables.services.secrets.exceptions import UndeclaredSecretError
from tables.services.session_manager_service import SessionManagerService


@pytest.mark.django_db
class TestSessionAborts:
    def test_session_ends_in_error_and_publishes_nothing(self, org, graph, monkeypatch):
        """Mirrors TestUnresolvableSecretFailsTheSession: run_session's existing
        try/except marks the session ERROR, records a reason and publishes nothing.
        """
        start = StartNode.objects.create(graph=graph, variables={"variables": {}})
        node = PythonNode.objects.create(
            graph=graph,
            node_name="Python-Node #3",
            python_code=PythonCode.objects.create(code=DECLARING_CODE),
        )
        Edge.objects.create(graph=graph, start_node_id=start.pk, end_node_id=node.pk)

        published = []
        service = SessionManagerService()
        monkeypatch.setattr(
            service.redis_service.redis_client,
            "publish",
            lambda channel, message: published.append(message) or 2,
        )

        with pytest.raises(UndeclaredSecretError):
            service.run_session(graph_id=graph.pk, variables={})

        session = Session.objects.filter(graph_id=graph.pk).latest("pk")
        assert session.status == Session.SessionStatus.ERROR
        reason = session.status_data["reason"]
        assert "Python-Node #3" in reason
        assert "VAL_KEY" in reason
        assert not published, "a session with an undeclared secret was published"

    def test_a_fully_declared_graph_still_runs(self, org, graph, secret, monkeypatch):
        """The inverse matters as much: proving the gate closes is worthless if it
        also blocks a correctly declared flow."""
        python_code = PythonCode.objects.create(code=DECLARING_CODE)
        python_code.secrets.set([secret])
        start = StartNode.objects.create(graph=graph, variables={"variables": {}})
        node = PythonNode.objects.create(
            graph=graph, node_name="declared", python_code=python_code
        )
        Edge.objects.create(graph=graph, start_node_id=start.pk, end_node_id=node.pk)

        published = []
        service = SessionManagerService()
        monkeypatch.setattr(
            service.redis_service.redis_client,
            "publish",
            lambda channel, message: published.append(message) or 2,
        )

        session_id = service.run_session(graph_id=graph.pk, variables={})

        session = Session.objects.get(pk=session_id)
        assert session.status != Session.SessionStatus.ERROR
        assert published
        # The declared plaintext reaches crew on the wire.
        assert "sk-val" in "".join(published)
