"""Each usage source, tested through collect() with no HTTP and no aggregation.

These assert the exact UsageHit fields the wire contract depends on, so a source
that silently stops reporting a graph id or a node type fails here rather than in
the dialog.
"""

import pytest

from tables.models import (
    EmbeddingConfig,
    LLMConfig,
    McpTool,
    RealtimeConfig,
    RealtimeTranscriptionConfig,
)
from tables.models import PythonCode, PythonCodeTool
from tables.models.embedding_models import EmbeddingModel
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    ConditionalEdge,
    Edge,
    Graph,
    PythonNode,
    StartNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.models.llm_models import (
    LLMModel,
    RealtimeModel,
    RealtimeTranscriptionModel,
)
from tables.models.rbac_models import Organization
from tables.services.secrets import secret_service
from tables.services.secrets.usage_sources import (
    CATEGORY_LLM_CONFIGS,
    CATEGORY_TOOLS,
    NODE_TYPE_CLASSIFICATION_TABLE,
    NODE_TYPE_EDGE,
    NODE_TYPE_PYTHON,
    NODE_TYPE_TELEGRAM_TRIGGER,
    NODE_TYPE_WEBHOOK_TRIGGER,
    ConditionalEdgeUsageSource,
    FkUsageSource,
    FlowCodeUsageSource,
    FlowFkUsageSource,
    ToolCodeUsageSource,
)

DECLARING_CODE = 'def main(**kwargs):\n    return get_secret("USAGE_KEY")\n'


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org SecretUsageSources")


@pytest.fixture
def secret(org):
    return secret_service.create(text="sk-usage-1", org=org, name="USAGE_KEY")


@pytest.fixture
def names(secret):
    """The {name: id} map every source receives."""
    return {secret.name: secret.pk}


@pytest.mark.django_db
class TestFkUsageSource:
    def test_llm_config_reports_its_custom_name(self, org, secret, names):
        model = LLMModel.objects.create(name="gpt-4o-usage", llm_provider=None, org=org)
        LLMConfig.objects.create(
            custom_name="prod cfg", model=model, org=org, api_key_secret=secret
        )

        source = FkUsageSource(
            model=LLMConfig,
            secret_field="api_key_secret",
            category=CATEGORY_LLM_CONFIGS,
            name_field="custom_name",
        )
        hits = source.collect(org_id=org.id, secret_names=names)

        assert len(hits) == 1
        assert hits[0].secret_id == secret.pk
        assert hits[0].category == CATEGORY_LLM_CONFIGS
        assert hits[0].resource_name == "prod cfg"
        assert hits[0].resource_id is None
        assert hits[0].node_name is None

    def test_a_config_with_no_secret_is_not_reported(self, org, names):
        model = LLMModel.objects.create(
            name="gpt-4o-nosecret", llm_provider=None, org=org
        )
        LLMConfig.objects.create(custom_name="no key", model=model, org=org)

        source = FkUsageSource(
            model=LLMConfig,
            secret_field="api_key_secret",
            category=CATEGORY_LLM_CONFIGS,
            name_field="custom_name",
        )

        assert source.collect(org_id=org.id, secret_names=names) == []

    def test_another_orgs_config_is_not_reported(self, org, secret, names):
        """Scoping is on the resource too, not only the secret: a config in another
        org is invisible to this org even if it somehow points at this secret."""
        other = Organization.objects.create(name="Org SecretUsageSources Other")
        model = LLMModel.objects.create(
            name="gpt-4o-foreign", llm_provider=None, org=other
        )
        LLMConfig.objects.create(
            custom_name="foreign cfg", model=model, org=other, api_key_secret=secret
        )

        source = FkUsageSource(
            model=LLMConfig,
            secret_field="api_key_secret",
            category=CATEGORY_LLM_CONFIGS,
            name_field="custom_name",
        )

        assert source.collect(org_id=org.id, secret_names=names) == []

    def test_mcp_tool_reports_under_tools_by_name(self, org, secret, names):
        McpTool.objects.create(
            name="search tool",
            transport="https://example.com/sse",
            tool_name="search",
            org=org,
            auth_secret=secret,
        )

        source = FkUsageSource(
            model=McpTool,
            secret_field="auth_secret",
            category=CATEGORY_TOOLS,
            name_field="name",
        )
        hits = source.collect(org_id=org.id, secret_names=names)

        assert [(hit.category, hit.resource_name) for hit in hits] == [
            (CATEGORY_TOOLS, "search tool")
        ]

    def test_embedding_and_realtime_configs_all_report(self, org, secret, names):
        """All four config models fold into one category, so all four must work."""
        EmbeddingConfig.objects.create(
            custom_name="embed cfg",
            model=EmbeddingModel.objects.create(name="embed-usage", org=org),
            org=org,
            api_key_secret=secret,
        )
        # Each realtime config names its model FK after the model, not "model".
        RealtimeConfig.objects.create(
            custom_name="rt cfg",
            realtime_model=RealtimeModel.objects.create(name="rt-usage", org=org),
            org=org,
            api_key_secret=secret,
        )
        RealtimeTranscriptionConfig.objects.create(
            custom_name="rtt cfg",
            realtime_transcription_model=RealtimeTranscriptionModel.objects.create(
                name="rtt-usage", org=org
            ),
            org=org,
            api_key_secret=secret,
        )

        found = []
        for model in (
            EmbeddingConfig,
            RealtimeConfig,
            RealtimeTranscriptionConfig,
        ):
            source = FkUsageSource(
                model=model,
                secret_field="api_key_secret",
                category=CATEGORY_LLM_CONFIGS,
                name_field="custom_name",
            )
            found.extend(
                hit.resource_name
                for hit in source.collect(org_id=org.id, secret_names=names)
            )

        assert sorted(found) == ["embed cfg", "rt cfg", "rtt cfg"]


@pytest.mark.django_db
class TestFlowFkUsageSource:
    def test_telegram_node_reports_as_a_flow_node(self, org, secret, names):
        graph = Graph.objects.create(name="Telegram flow", org=org)
        TelegramTriggerNode.objects.create(
            node_name="notify",
            graph=graph,
            telegram_bot_api_key_secret=secret,
        )

        source = FlowFkUsageSource(
            model=TelegramTriggerNode,
            secret_field="telegram_bot_api_key_secret",
            node_type=NODE_TYPE_TELEGRAM_TRIGGER,
        )
        hits = source.collect(org_id=org.id, secret_names=names)

        assert len(hits) == 1
        hit = hits[0]
        assert hit.category == "flows"
        assert hit.resource_id == graph.pk
        assert hit.resource_name == "Telegram flow"
        assert hit.node_name == "notify"
        assert hit.node_type == NODE_TYPE_TELEGRAM_TRIGGER

    def test_a_node_in_another_orgs_graph_is_not_reported(self, org, secret, names):
        other = Organization.objects.create(name="Org SecretUsageSources Flow Other")
        graph = Graph.objects.create(name="Foreign flow", org=other)
        TelegramTriggerNode.objects.create(
            node_name="foreign notify",
            graph=graph,
            telegram_bot_api_key_secret=secret,
        )

        source = FlowFkUsageSource(
            model=TelegramTriggerNode,
            secret_field="telegram_bot_api_key_secret",
            node_type=NODE_TYPE_TELEGRAM_TRIGGER,
        )

        assert source.collect(org_id=org.id, secret_names=names) == []


@pytest.mark.django_db
class TestFlowCodeUsageSource:
    def test_python_node_declaring_a_secret_is_reported(self, org, secret, names):
        graph = Graph.objects.create(name="Python flow", org=org)
        python_code = PythonCode.objects.create(code=DECLARING_CODE)
        # The declaration is the M2M — usage reports what a node is allowed to
        # read, because that is what deleting the secret would take away.
        python_code.secrets.set([secret])
        PythonNode.objects.create(
            graph=graph, node_name="charge_card", python_code=python_code
        )

        source = FlowCodeUsageSource(
            model=PythonNode, code_field="python_code", node_type=NODE_TYPE_PYTHON
        )
        hits = source.collect(org_id=org.id, secret_names=names)

        assert len(hits) == 1
        hit = hits[0]
        assert hit.secret_id == secret.pk
        assert hit.category == "flows"
        assert hit.resource_id == graph.pk
        assert hit.resource_name == "Python flow"
        assert hit.node_name == "charge_card"
        assert hit.node_type == NODE_TYPE_PYTHON

    def test_a_name_in_code_without_a_declaration_is_not_usage(self, org, names):
        """Usage means declared. A node that merely names a secret is a node that
        cannot be saved and that the session gate rejects — not a user of it.

        The parser-behaviour cases that used to live here (comment-only,
        unparseable, unknown name) moved to test_secret_declaration_validator.py,
        which is where the parser still runs.
        """
        graph = Graph.objects.create(name="Mention flow", org=org)
        PythonNode.objects.create(
            graph=graph,
            node_name="mentions_only",
            python_code=PythonCode.objects.create(code=DECLARING_CODE),
        )

        source = FlowCodeUsageSource(
            model=PythonNode, code_field="python_code", node_type=NODE_TYPE_PYTHON
        )

        assert source.collect(org_id=org.id, secret_names=names) == []

    def test_a_declared_but_unreferenced_secret_is_usage(self, org, secret, names):
        """Over-reporting is the safe direction for a deletion guard: being warned
        about something harmless beats deleting something that breaks a flow."""
        graph = Graph.objects.create(name="Unused decl flow", org=org)
        python_code = PythonCode.objects.create(
            code="def main(**kwargs):\n    return 1\n"
        )
        python_code.secrets.set([secret])
        PythonNode.objects.create(
            graph=graph, node_name="unused_decl", python_code=python_code
        )

        source = FlowCodeUsageSource(
            model=PythonNode, code_field="python_code", node_type=NODE_TYPE_PYTHON
        )

        assert len(source.collect(org_id=org.id, secret_names=names)) == 1

    def test_webhook_trigger_node_is_reported(self, org, secret, names):
        graph = Graph.objects.create(name="Webhook flow", org=org)
        python_code = PythonCode.objects.create(code=DECLARING_CODE)
        python_code.secrets.set([secret])
        WebhookTriggerNode.objects.create(
            graph=graph, node_name="on_hook", python_code=python_code
        )

        source = FlowCodeUsageSource(
            model=WebhookTriggerNode,
            code_field="python_code",
            node_type=NODE_TYPE_WEBHOOK_TRIGGER,
        )
        hits = source.collect(org_id=org.id, secret_names=names)

        assert [(hit.node_name, hit.node_type) for hit in hits] == [
            ("on_hook", NODE_TYPE_WEBHOOK_TRIGGER)
        ]

    def test_cdt_pre_and_post_are_separate_sources(self, org, secret, names):
        """Two source entries see the same node. Collapsing them into one node
        entry is aggregation's job, not the source's."""
        graph = Graph.objects.create(name="CDT flow", org=org)
        pre_code = PythonCode.objects.create(code=DECLARING_CODE)
        pre_code.secrets.set([secret])
        post_code = PythonCode.objects.create(code=DECLARING_CODE)
        post_code.secrets.set([secret])
        ClassificationDecisionTableNode.objects.create(
            graph=graph,
            node_name="classify",
            pre_python_code=pre_code,
            post_python_code=post_code,
        )

        pre = FlowCodeUsageSource(
            model=ClassificationDecisionTableNode,
            code_field="pre_python_code",
            node_type=NODE_TYPE_CLASSIFICATION_TABLE,
        )
        post = FlowCodeUsageSource(
            model=ClassificationDecisionTableNode,
            code_field="post_python_code",
            node_type=NODE_TYPE_CLASSIFICATION_TABLE,
        )

        assert len(pre.collect(org_id=org.id, secret_names=names)) == 1
        assert len(post.collect(org_id=org.id, secret_names=names)) == 1

    def test_a_cdt_with_no_pre_code_is_not_reported(self, org, names):
        """pre_python_code is nullable; a NULL FK must not blow up the join."""
        graph = Graph.objects.create(name="CDT post only", org=org)
        ClassificationDecisionTableNode.objects.create(
            graph=graph,
            node_name="post only",
            post_python_code=PythonCode.objects.create(code=DECLARING_CODE),
        )

        pre = FlowCodeUsageSource(
            model=ClassificationDecisionTableNode,
            code_field="pre_python_code",
            node_type=NODE_TYPE_CLASSIFICATION_TABLE,
        )

        assert pre.collect(org_id=org.id, secret_names=names) == []


@pytest.mark.django_db
class TestToolCodeUsageSource:
    def test_own_org_tool_is_reported(self, org, secret, names):
        python_code = PythonCode.objects.create(code=DECLARING_CODE)
        python_code.secrets.set([secret])
        PythonCodeTool.objects.create(
            name="Stripe refund",
            description="refund",
            org=org,
            built_in=False,
            python_code=python_code,
        )

        hits = ToolCodeUsageSource().collect(org_id=org.id, secret_names=names)

        assert [(hit.category, hit.resource_name) for hit in hits] == [
            ("tools", "Stripe refund")
        ]

    def test_built_in_tool_counts_for_the_querying_org(self, org, secret, names):
        """Built-ins are global (org=NULL) but resolve the *querying* org's secret
        at run time, so deleting it really would break this org's use of them."""
        python_code = PythonCode.objects.create(code=DECLARING_CODE)
        python_code.secrets.set([secret])
        PythonCodeTool.objects.create(
            name="Built-in fetcher",
            description="built in",
            org=None,
            built_in=True,
            python_code=python_code,
        )

        hits = ToolCodeUsageSource().collect(org_id=org.id, secret_names=names)

        assert [hit.resource_name for hit in hits] == ["Built-in fetcher"]

    def test_another_orgs_tool_is_not_reported(self, org, names):
        other = Organization.objects.create(name="Org SecretUsageSources Tool Other")
        PythonCodeTool.objects.create(
            name="Foreign tool",
            description="foreign",
            org=other,
            built_in=False,
            python_code=PythonCode.objects.create(code=DECLARING_CODE),
        )

        assert ToolCodeUsageSource().collect(org_id=org.id, secret_names=names) == []


@pytest.mark.django_db
class TestConditionalEdgeUsageSource:
    def test_edge_is_named_after_its_source_node(self, org, secret, names):
        """A ConditionalEdge has no name of its own, so it borrows the identity of
        the node it branches off — the same one converter_service uses."""
        graph = Graph.objects.create(name="Branching flow", org=org)
        start = StartNode.objects.create(graph=graph, variables={"variables": {}})
        router = PythonNode.objects.create(
            graph=graph,
            node_name="route_by_tier",
            python_code=PythonCode.objects.create(
                code="def main(**kwargs):\n    return 1\n"
            ),
        )
        Edge.objects.create(graph=graph, start_node_id=start.pk, end_node_id=router.pk)
        edge_code = PythonCode.objects.create(code=DECLARING_CODE)
        edge_code.secrets.set([secret])
        ConditionalEdge.objects.create(
            graph=graph, source_node_id=router.pk, python_code=edge_code
        )

        hits = ConditionalEdgeUsageSource().collect(org_id=org.id, secret_names=names)

        assert len(hits) == 1
        hit = hits[0]
        assert hit.secret_id == secret.pk
        assert hit.category == "flows"
        assert hit.resource_id == graph.pk
        assert hit.node_type == NODE_TYPE_EDGE
        # The plain node name, with no " #<id>" suffix — every other flow source
        # reports node_name verbatim and the dialog must read consistently.
        assert hit.node_name == "route_by_tier"

    def test_edge_with_no_source_node_falls_back_to_its_own_id(
        self, org, secret, names
    ):
        graph = Graph.objects.create(name="Orphan branch flow", org=org)
        edge_code = PythonCode.objects.create(code=DECLARING_CODE)
        edge_code.secrets.set([secret])
        edge = ConditionalEdge.objects.create(
            graph=graph, source_node_id=None, python_code=edge_code
        )

        hits = ConditionalEdgeUsageSource().collect(org_id=org.id, secret_names=names)

        assert [hit.node_name for hit in hits] == [f"Conditional edge #{edge.pk}"]


@pytest.mark.django_db
def test_registry_covers_every_declared_source():
    """Twelve sources: six FK-declared and six code-declared. A source added to the
    module but forgotten in the registry is invisible to both endpoints, which is a
    silent under-report — so the count is asserted."""
    from tables.services.secrets.usage_sources import USAGE_SOURCES

    assert len(USAGE_SOURCES) == 12
