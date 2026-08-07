"""Each usage source, tested through the registry with no HTTP and no aggregation.

These assert the exact UsageHit fields the wire contract depends on, so a source
that silently stops reporting a graph id or a node type fails here rather than in
the dialog.

Sources are looked up from USAGE_SOURCES rather than constructed locally: the
registry derives half its entries from PYTHON_CODE_SITES, so a wrong secret_path or
org_path is a live failure mode, and a locally-built instance would assert only that
the dataclass works while the configured one stayed broken.
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
    CATEGORY_FLOWS,
    CATEGORY_LLM_CONFIGS,
    CATEGORY_TOOLS,
    NODE_TYPE_TELEGRAM_TRIGGER,
    USAGE_SOURCES,
)
from tables.services.secrets.python_code_sites import (
    NODE_TYPE_CLASSIFICATION_TABLE,
    NODE_TYPE_EDGE,
    NODE_TYPE_PYTHON,
    NODE_TYPE_WEBHOOK_TRIGGER,
)

DECLARING_CODE = 'def main(**kwargs):\n    return get_secret("USAGE_KEY")\n'


def _source(*, model, secret_path: str | None = None):
    """The registry's configured source for this model.

    secret_path disambiguates ClassificationDecisionTableNode, which contributes two
    entries (pre and post).
    """
    matches = [
        source
        for source in USAGE_SOURCES
        if source.model is model
        and (secret_path is None or source.secret_path == secret_path)
    ]
    assert len(matches) == 1, (
        f"expected exactly one registry source for {model.__name__}"
        f"{f' at {secret_path}' if secret_path else ''}, found {len(matches)}"
    )
    return matches[0]


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org SecretUsageSources")


@pytest.fixture
def secret(org):
    return secret_service.create(text="sk-usage-1", org=org, name="USAGE_KEY")


@pytest.fixture
def ids(secret):
    """The secret id set every source receives."""
    return {secret.pk}


@pytest.mark.django_db
class TestForeignKeySources:
    def test_llm_config_reports_its_custom_name(self, org, secret, ids):
        model = LLMModel.objects.create(name="gpt-4o-usage", llm_provider=None, org=org)
        LLMConfig.objects.create(
            custom_name="prod cfg", model=model, org=org, api_key_secret=secret
        )

        hits = _source(model=LLMConfig).collect(org_id=org.id, secret_ids=ids)

        assert len(hits) == 1
        assert hits[0].secret_id == secret.pk
        assert hits[0].category == CATEGORY_LLM_CONFIGS
        assert hits[0].resource_name == "prod cfg"
        assert hits[0].resource_id is None
        assert hits[0].node_name is None

    def test_a_config_with_no_secret_is_not_reported(self, org, ids):
        model = LLMModel.objects.create(
            name="gpt-4o-nosecret", llm_provider=None, org=org
        )
        LLMConfig.objects.create(custom_name="no key", model=model, org=org)

        assert _source(model=LLMConfig).collect(org_id=org.id, secret_ids=ids) == []

    def test_another_orgs_config_is_not_reported(self, org, secret, ids):
        """Scoping is on the resource too, not only the secret: a config in another
        org is invisible to this org even if it somehow points at this secret."""
        other = Organization.objects.create(name="Org SecretUsageSources Other")
        model = LLMModel.objects.create(
            name="gpt-4o-foreign", llm_provider=None, org=other
        )
        LLMConfig.objects.create(
            custom_name="foreign cfg", model=model, org=other, api_key_secret=secret
        )

        assert _source(model=LLMConfig).collect(org_id=org.id, secret_ids=ids) == []

    def test_mcp_tool_reports_under_tools_by_name(self, org, secret, ids):
        McpTool.objects.create(
            name="search tool",
            transport="https://example.com/sse",
            tool_name="search",
            org=org,
            auth_secret=secret,
        )

        hits = _source(model=McpTool).collect(org_id=org.id, secret_ids=ids)

        assert [(hit.category, hit.resource_name) for hit in hits] == [
            (CATEGORY_TOOLS, "search tool")
        ]

    def test_embedding_and_realtime_configs_all_report(self, org, secret, ids):
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
            found.extend(
                hit.resource_name
                for hit in _source(model=model).collect(org_id=org.id, secret_ids=ids)
            )

        assert sorted(found) == ["embed cfg", "rt cfg", "rtt cfg"]


@pytest.mark.django_db
class TestFlowForeignKeySource:
    def test_telegram_node_reports_as_a_flow_node(self, org, secret, ids):
        graph = Graph.objects.create(name="Telegram flow", org=org)
        TelegramTriggerNode.objects.create(
            node_name="notify",
            graph=graph,
            telegram_bot_api_key_secret=secret,
        )

        hits = _source(model=TelegramTriggerNode).collect(org_id=org.id, secret_ids=ids)

        assert len(hits) == 1
        hit = hits[0]
        assert hit.category == CATEGORY_FLOWS
        assert hit.resource_id == graph.pk
        assert hit.resource_name == "Telegram flow"
        assert hit.node_name == "notify"
        assert hit.node_type == NODE_TYPE_TELEGRAM_TRIGGER

    def test_a_node_in_another_orgs_graph_is_not_reported(self, org, secret, ids):
        other = Organization.objects.create(name="Org SecretUsageSources Flow Other")
        graph = Graph.objects.create(name="Foreign flow", org=other)
        TelegramTriggerNode.objects.create(
            node_name="foreign notify",
            graph=graph,
            telegram_bot_api_key_secret=secret,
        )

        assert (
            _source(model=TelegramTriggerNode).collect(org_id=org.id, secret_ids=ids)
            == []
        )


@pytest.mark.django_db
class TestDeclarationSources:
    def test_python_node_declaring_a_secret_is_reported(self, org, secret, ids):
        graph = Graph.objects.create(name="Python flow", org=org)
        python_code = PythonCode.objects.create(code=DECLARING_CODE)
        # The declaration is the M2M — usage reports what a node is allowed to
        # read, because that is what deleting the secret would take away.
        python_code.secrets.set([secret])
        PythonNode.objects.create(
            graph=graph, node_name="charge_card", python_code=python_code
        )

        hits = _source(model=PythonNode).collect(org_id=org.id, secret_ids=ids)

        assert len(hits) == 1
        hit = hits[0]
        assert hit.secret_id == secret.pk
        assert hit.category == CATEGORY_FLOWS
        assert hit.resource_id == graph.pk
        assert hit.resource_name == "Python flow"
        assert hit.node_name == "charge_card"
        assert hit.node_type == NODE_TYPE_PYTHON

    def test_a_name_in_code_without_a_declaration_is_not_usage(self, org, ids):
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

        assert _source(model=PythonNode).collect(org_id=org.id, secret_ids=ids) == []

    def test_a_declared_but_unreferenced_secret_is_usage(self, org, secret, ids):
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

        assert (
            len(_source(model=PythonNode).collect(org_id=org.id, secret_ids=ids)) == 1
        )

    def test_webhook_trigger_node_is_reported(self, org, secret, ids):
        graph = Graph.objects.create(name="Webhook flow", org=org)
        python_code = PythonCode.objects.create(code=DECLARING_CODE)
        python_code.secrets.set([secret])
        WebhookTriggerNode.objects.create(
            graph=graph, node_name="on_hook", python_code=python_code
        )

        hits = _source(model=WebhookTriggerNode).collect(org_id=org.id, secret_ids=ids)

        assert [(hit.node_name, hit.node_type) for hit in hits] == [
            ("on_hook", NODE_TYPE_WEBHOOK_TRIGGER)
        ]

    def test_cdt_pre_and_post_are_separate_sources(self, org, secret, ids):
        """Two registry entries see the same node. Collapsing them into one node
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

        pre = _source(
            model=ClassificationDecisionTableNode,
            secret_path="pre_python_code__secrets__id",
        )
        post = _source(
            model=ClassificationDecisionTableNode,
            secret_path="post_python_code__secrets__id",
        )

        assert len(pre.collect(org_id=org.id, secret_ids=ids)) == 1
        assert len(post.collect(org_id=org.id, secret_ids=ids)) == 1
        assert pre.node_type == post.node_type == NODE_TYPE_CLASSIFICATION_TABLE

    def test_a_cdt_with_no_pre_code_is_not_reported(self, org, ids):
        """pre_python_code is nullable; a NULL FK must not blow up the join."""
        graph = Graph.objects.create(name="CDT post only", org=org)
        ClassificationDecisionTableNode.objects.create(
            graph=graph,
            node_name="post only",
            post_python_code=PythonCode.objects.create(code=DECLARING_CODE),
        )

        pre = _source(
            model=ClassificationDecisionTableNode,
            secret_path="pre_python_code__secrets__id",
        )

        assert pre.collect(org_id=org.id, secret_ids=ids) == []


@pytest.mark.django_db
class TestPythonCodeToolSource:
    def test_own_org_tool_is_reported(self, org, secret, ids):
        python_code = PythonCode.objects.create(code=DECLARING_CODE)
        python_code.secrets.set([secret])
        PythonCodeTool.objects.create(
            name="Stripe refund",
            description="refund",
            org=org,
            built_in=False,
            python_code=python_code,
        )

        hits = _source(model=PythonCodeTool).collect(org_id=org.id, secret_ids=ids)

        assert [(hit.category, hit.resource_name) for hit in hits] == [
            (CATEGORY_TOOLS, "Stripe refund")
        ]

    def test_built_in_tool_counts_for_the_querying_org(self, org, secret, ids):
        """Built-ins are global (org=NULL) but resolve the *querying* org's secret
        at run time, so deleting it really would break this org's use of them.

        This is what org_path=None buys: the registry derives it from the
        PythonCodeTool site, so an org_id filter never gets applied here.
        """
        python_code = PythonCode.objects.create(code=DECLARING_CODE)
        python_code.secrets.set([secret])
        PythonCodeTool.objects.create(
            name="Built-in fetcher",
            description="built in",
            org=None,
            built_in=True,
            python_code=python_code,
        )

        hits = _source(model=PythonCodeTool).collect(org_id=org.id, secret_ids=ids)

        assert [hit.resource_name for hit in hits] == ["Built-in fetcher"]

    def test_another_orgs_tool_is_not_reported(self, org, ids):
        other = Organization.objects.create(name="Org SecretUsageSources Tool Other")
        PythonCodeTool.objects.create(
            name="Foreign tool",
            description="foreign",
            org=other,
            built_in=False,
            python_code=PythonCode.objects.create(code=DECLARING_CODE),
        )

        assert (
            _source(model=PythonCodeTool).collect(org_id=org.id, secret_ids=ids) == []
        )


@pytest.mark.django_db
class TestConditionalEdgeSource:
    def test_edge_is_named_after_its_source_node(self, org, secret, ids):
        """A ConditionalEdge has no name of its own, so it borrows the identity of
        the node it branches off — the same one converter_service uses. name_field
        is None in the registry, which is what selects that branch."""
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

        source = _source(model=ConditionalEdge)
        assert source.name_field is None
        hits = source.collect(org_id=org.id, secret_ids=ids)

        assert len(hits) == 1
        hit = hits[0]
        assert hit.secret_id == secret.pk
        assert hit.category == CATEGORY_FLOWS
        assert hit.resource_id == graph.pk
        assert hit.node_type == NODE_TYPE_EDGE
        # The plain node name, with no " #<id>" suffix — every other flow source
        # reports node_name verbatim and the dialog must read consistently.
        assert hit.node_name == "route_by_tier"

    def test_edge_with_no_source_node_falls_back_to_its_own_id(self, org, secret, ids):
        graph = Graph.objects.create(name="Orphan branch flow", org=org)
        edge_code = PythonCode.objects.create(code=DECLARING_CODE)
        edge_code.secrets.set([secret])
        edge = ConditionalEdge.objects.create(
            graph=graph, source_node_id=None, python_code=edge_code
        )

        hits = _source(model=ConditionalEdge).collect(org_id=org.id, secret_ids=ids)

        assert [hit.node_name for hit in hits] == [f"Conditional edge #{edge.pk}"]


@pytest.mark.django_db
class TestCountPairs:
    """The counts projection. Two columns, and the key carries the dedup rule.

    collect() and count_pairs() must agree about *which rows match* — they share
    _scoped, so the risk is not the filter but the key, which only exists here.
    """

    def test_a_flow_key_is_the_graph_not_the_node(self, org, secret, ids):
        """Why a flow counts once however many of its nodes use the secret: two
        nodes in one graph produce two rows with an identical key, and UNION's
        DISTINCT is what collapses them."""
        graph = Graph.objects.create(name="Two node flow", org=org)
        for node_name in ("first", "second"):
            python_code = PythonCode.objects.create(code=DECLARING_CODE)
            python_code.secrets.set([secret])
            PythonNode.objects.create(
                graph=graph, node_name=node_name, python_code=python_code
            )

        pairs = list(
            _source(model=PythonNode).count_pairs(org_id=org.id, secret_ids=ids)
        )

        assert len(pairs) == 2
        assert {key for _, key in pairs} == {f"flows:{graph.pk}"}
        assert {secret_id for secret_id, _ in pairs} == {secret.pk}

    def test_a_named_key_carries_its_category(self, org, secret, ids):
        """The prefix is what folds four config models into one llm_configs
        namespace, so a config and a tool sharing a name stay distinct."""
        LLMConfig.objects.create(
            custom_name="shared",
            model=LLMModel.objects.create(
                name="gpt-4o-key", llm_provider=None, org=org
            ),
            org=org,
            api_key_secret=secret,
        )
        McpTool.objects.create(
            name="shared",
            transport="https://example.com/sse",
            tool_name="search",
            org=org,
            auth_secret=secret,
        )

        config_keys = [
            key
            for _, key in _source(model=LLMConfig).count_pairs(
                org_id=org.id, secret_ids=ids
            )
        ]
        tool_keys = [
            key
            for _, key in _source(model=McpTool).count_pairs(
                org_id=org.id, secret_ids=ids
            )
        ]

        assert config_keys == ["llm_configs:shared"]
        assert tool_keys == ["tools:shared"]
        assert config_keys != tool_keys

    def test_every_source_projects_two_columns_of_matching_type(self, org, ids):
        """The union in counts() requires it: differing column counts or types make
        the combined query a hard error rather than a wrong number."""
        for source in USAGE_SOURCES:
            pairs = source.count_pairs(org_id=org.id, secret_ids=ids)
            assert (
                len(pairs.query.values_select or ())
                + len(pairs.query.annotation_select)
                == 2
            ), source.model.__name__

    def test_the_whole_registry_unions_without_error(self, org, secret, ids):
        """The integration the twelve projections exist for. Executed, not just
        compiled: mixed CharField/TextField name columns raise at compile time and
        an incompatible union raises at execution time."""
        first, *rest = [
            source.count_pairs(org_id=org.id, secret_ids=ids)
            for source in USAGE_SOURCES
        ]

        assert list(first.union(*rest)) == []


@pytest.mark.django_db
def test_registry_covers_every_declared_source():
    """Twelve sources: six FK-declared written out, six derived from
    PYTHON_CODE_SITES. A source added to the module but forgotten in the registry is
    invisible to both endpoints, which is a silent under-report."""
    from tables.services.secrets.python_code_sites import PYTHON_CODE_SITES

    assert len(USAGE_SOURCES) == 12
    # The derived half tracks PYTHON_CODE_SITES automatically; assert the link rather
    # than the number, so adding a Python-carrying model cannot break this test while
    # leaving the dialog under-reporting.
    derived = [
        source
        for source in USAGE_SOURCES
        if source.secret_path.endswith("__secrets__id")
    ]
    assert len(derived) == len(PYTHON_CODE_SITES)
