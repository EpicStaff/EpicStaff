"""Aggregation: how the sources become the two surfaces.

The load-bearing property is that counts() and summary() agree — usage_count on
the list must always equal the detail endpoint's total for the same secret, or the
table chip and the dialog headline contradict each other. They now reach that answer
by different routes (one union query vs. a full UsageHit sweep), so the agreement
tests below are what hold the two dedup rules together.
"""

import pytest

from tables.models import EmbeddingConfig, LLMConfig, McpTool, PythonCode
from tables.models.embedding_models import EmbeddingModel
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    ConditionalEdge,
    Graph,
    PythonNode,
)
from tables.models.llm_models import LLMModel, RealtimeConfig, RealtimeModel
from tables.models.rbac_models import Organization
from tables.services.secrets import secret_service
from tables.services.secrets.usage_service import secret_usage_service

DECLARING_CODE = 'def main(**kwargs):\n    return get_secret("USAGE_KEY")\n'


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org SecretUsageService")


@pytest.fixture
def secret(org):
    return secret_service.create(text="sk-agg", org=org, name="USAGE_KEY")


@pytest.mark.django_db
class TestCounts:
    def test_every_org_secret_gets_an_entry_including_zero(self, org, secret):
        """Never sparse: a missing key and a genuine zero must not be confusable,
        or a broken sweep silently renders as "unused"."""
        unused = secret_service.create(text="sk-unused", org=org, name="UNUSED_KEY")

        counts = secret_usage_service.counts(org_id=org.id)

        assert set(counts) == {secret.pk, unused.pk}
        assert counts[secret.pk] == 0
        assert counts[unused.pk] == 0

    def test_a_flow_counts_once_however_many_nodes_use_the_secret(self, org, secret):
        graph = Graph.objects.create(name="Multi-node flow", org=org)
        # Each node gets its own declared PythonCode: the declaration is per
        # PythonCode, and these three nodes do not share one.
        for node_name in ("first", "second", "third"):
            python_code = PythonCode.objects.create(code=DECLARING_CODE)
            python_code.secrets.set([secret])
            PythonNode.objects.create(
                graph=graph, node_name=node_name, python_code=python_code
            )

        assert secret_usage_service.counts(org_id=org.id)[secret.pk] == 1

    def test_counts_sum_across_categories(self, org, secret):
        graph = Graph.objects.create(name="Counted flow", org=org)
        python_code = PythonCode.objects.create(code=DECLARING_CODE)
        python_code.secrets.set([secret])
        PythonNode.objects.create(
            graph=graph, node_name="node", python_code=python_code
        )
        McpTool.objects.create(
            name="counted tool",
            transport="https://example.com/sse",
            tool_name="search",
            org=org,
            auth_secret=secret,
        )
        LLMConfig.objects.create(
            custom_name="counted cfg",
            model=LLMModel.objects.create(
                name="gpt-4o-counted", llm_provider=None, org=org
            ),
            org=org,
            api_key_secret=secret,
        )

        assert secret_usage_service.counts(org_id=org.id)[secret.pk] == 3

    def test_an_org_with_no_secrets_returns_an_empty_map(self, db):
        empty = Organization.objects.create(name="Org SecretUsageService Empty")

        assert secret_usage_service.counts(org_id=empty.id) == {}

    def test_the_same_name_in_another_org_does_not_bleed(self, org, secret):
        """Names are org-scoped by UniqueConstraint(org, name), so an identically
        named secret elsewhere is a different credential entirely."""
        other = Organization.objects.create(name="Org SecretUsageService Other")
        other_secret = secret_service.create(
            text="sk-other", org=other, name="USAGE_KEY"
        )
        other_graph = Graph.objects.create(name="Other flow", org=other)
        # The other org's node genuinely declares its own same-named secret —
        # otherwise this test would pass trivially, since an undeclared node is
        # invisible to usage regardless of org.
        other_code = PythonCode.objects.create(code=DECLARING_CODE)
        other_code.secrets.set([other_secret])
        PythonNode.objects.create(
            graph=other_graph, node_name="other node", python_code=other_code
        )

        assert secret_usage_service.counts(org_id=org.id)[secret.pk] == 0


@pytest.mark.django_db
class TestSummary:
    def test_unused_secret_returns_zero_and_no_categories(self, org, secret):
        assert secret_usage_service.summary(secret=secret) == {
            "total": 0,
            "categories": [],
        }

    def test_a_category_with_no_items_is_omitted(self, org, secret):
        """Emitting only non-empty categories is also why the frontend's
        ngrok_config and voice_twilio never appear: nothing produces hits."""
        McpTool.objects.create(
            name="only tool",
            transport="https://example.com/sse",
            tool_name="search",
            org=org,
            auth_secret=secret,
        )

        summary = secret_usage_service.summary(secret=secret)

        assert [category["key"] for category in summary["categories"]] == ["tools"]

    def test_categories_come_in_a_fixed_order(self, org, secret):
        graph = Graph.objects.create(name="Ordered flow", org=org)
        python_code = PythonCode.objects.create(code=DECLARING_CODE)
        python_code.secrets.set([secret])
        PythonNode.objects.create(
            graph=graph, node_name="node", python_code=python_code
        )
        McpTool.objects.create(
            name="ordered tool",
            transport="https://example.com/sse",
            tool_name="search",
            org=org,
            auth_secret=secret,
        )
        LLMConfig.objects.create(
            custom_name="ordered cfg",
            model=LLMModel.objects.create(
                name="gpt-4o-ordered", llm_provider=None, org=org
            ),
            org=org,
            api_key_secret=secret,
        )

        summary = secret_usage_service.summary(secret=secret)

        assert [category["key"] for category in summary["categories"]] == [
            "flows",
            "tools",
            "llm_configs",
        ]

    def test_cdt_pre_and_post_collapse_to_one_node(self, org, secret):
        """Two sources see the same node. The dialog must list it once."""
        graph = Graph.objects.create(name="CDT agg flow", org=org)
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

        summary = secret_usage_service.summary(secret=secret)
        flows = summary["categories"][0]

        assert flows["key"] == "flows"
        assert len(flows["items"]) == 1
        assert flows["items"][0]["nodes"] == [
            {"name": "classify", "node_type": "classification-decision-table"}
        ]
        assert summary["total"] == 1

    def test_one_flow_with_several_nodes_is_one_item_with_several_nodes(
        self, org, secret
    ):
        graph = Graph.objects.create(name="Grouped flow", org=org)
        for node_name in ("alpha", "beta"):
            python_code = PythonCode.objects.create(code=DECLARING_CODE)
            python_code.secrets.set([secret])
            PythonNode.objects.create(
                graph=graph, node_name=node_name, python_code=python_code
            )

        summary = secret_usage_service.summary(secret=secret)
        items = summary["categories"][0]["items"]

        assert len(items) == 1
        assert items[0]["id"] == graph.pk
        assert items[0]["name"] == "Grouped flow"
        assert sorted(node["name"] for node in items[0]["nodes"]) == ["alpha", "beta"]
        assert summary["total"] == 1

    def test_two_configs_of_one_type_sharing_a_name_dedupe(self, org, secret):
        """RealtimeConfig has no per-org uniqueness on custom_name, so this is
        genuinely reachable. The items carry nothing but a name and the dialog
        tracks by it, so duplicates must collapse or Angular raises NG0955.

        Note the cost: these are two distinct resources reported as one, so the
        count under-reports. Rendering them separately is not an option while the
        item shape is {name} alone.
        """
        realtime_model = RealtimeModel.objects.create(name="rt-dupe", org=org)
        for _ in range(2):
            RealtimeConfig.objects.create(
                custom_name="same name",
                realtime_model=realtime_model,
                org=org,
                api_key_secret=secret,
            )

        summary = secret_usage_service.summary(secret=secret)

        assert summary["categories"][0]["items"] == [{"name": "same name"}]
        assert summary["total"] == 1

    def test_different_config_types_sharing_a_name_dedupe(self, org, secret):
        """Four models fold into the one llm_configs category, and per-model
        uniqueness cannot prevent a collision across them."""
        LLMConfig.objects.create(
            custom_name="prod",
            model=LLMModel.objects.create(
                name="gpt-4o-cross", llm_provider=None, org=org
            ),
            org=org,
            api_key_secret=secret,
        )
        EmbeddingConfig.objects.create(
            custom_name="prod",
            model=EmbeddingModel.objects.create(name="embed-cross", org=org),
            org=org,
            api_key_secret=secret,
        )

        summary = secret_usage_service.summary(secret=secret)

        assert summary["categories"][0]["items"] == [{"name": "prod"}]

    def test_total_equals_the_sum_of_category_item_counts(self, org, secret):
        graph = Graph.objects.create(name="Total flow", org=org)
        python_code = PythonCode.objects.create(code=DECLARING_CODE)
        python_code.secrets.set([secret])
        PythonNode.objects.create(
            graph=graph, node_name="node", python_code=python_code
        )
        McpTool.objects.create(
            name="total tool",
            transport="https://example.com/sse",
            tool_name="search",
            org=org,
            auth_secret=secret,
        )

        summary = secret_usage_service.summary(secret=secret)

        assert summary["total"] == sum(
            len(category["items"]) for category in summary["categories"]
        )

    def test_summary_total_matches_counts_for_the_same_secret(self, org, secret):
        """The invariant that keeps the table chip and the dialog headline honest."""
        graph = Graph.objects.create(name="Agreement flow", org=org)
        python_code = PythonCode.objects.create(code=DECLARING_CODE)
        python_code.secrets.set([secret])
        PythonNode.objects.create(
            graph=graph, node_name="node", python_code=python_code
        )
        McpTool.objects.create(
            name="agreement tool",
            transport="https://example.com/sse",
            tool_name="search",
            org=org,
            auth_secret=secret,
        )

        assert (
            secret_usage_service.summary(secret=secret)["total"]
            == secret_usage_service.counts(org_id=org.id)[secret.pk]
        )


@pytest.mark.django_db
class TestCountsQueryCost:
    """The reason counts() stopped going through collect().

    Before this, the list endpoint paid twelve source sweeps plus node-name
    resolution (a UNION query and one SELECT per node table) to render a column of
    integers it could get from two.
    """

    def test_two_queries_regardless_of_how_many_secrets_the_org_holds(
        self, org, secret, django_assert_num_queries
    ):
        for index in range(10):
            secret_service.create(text=f"sk-{index}", org=org, name=f"BULK_{index}")

        # One for the id set, one combined query for every reference.
        with django_assert_num_queries(2):
            secret_usage_service.counts(org_id=org.id)

    def test_two_queries_even_with_a_conditional_edge_in_play(
        self, org, secret, django_assert_num_queries
    ):
        """The specific regression. A ConditionalEdge is the only source whose detail
        path needs resolve_node_names, and that ran on the counts path too — so this
        case was the expensive one and must now cost the same as any other."""
        graph = Graph.objects.create(name="Edge cost flow", org=org)
        router = PythonNode.objects.create(
            graph=graph,
            node_name="route",
            python_code=PythonCode.objects.create(
                code="def main(**kwargs):\n    return 1\n"
            ),
        )
        edge_code = PythonCode.objects.create(code=DECLARING_CODE)
        edge_code.secrets.set([secret])
        ConditionalEdge.objects.create(
            graph=graph, source_node_id=router.pk, python_code=edge_code
        )

        with django_assert_num_queries(2):
            counts = secret_usage_service.counts(org_id=org.id)

        assert counts[secret.pk] == 1

    def test_an_empty_org_costs_one_query(self, db, django_assert_num_queries):
        """No secrets means nothing can reference them, so the union never runs."""
        empty = Organization.objects.create(name="Org SecretUsageService NoQueries")

        with django_assert_num_queries(1):
            assert secret_usage_service.counts(org_id=empty.id) == {}


@pytest.mark.django_db
class TestCountsDedupInSql:
    """Dedup moved from a Python set into UNION's DISTINCT, so each collapsing rule
    is a new code path even where summary() already asserted the same outcome."""

    def test_two_configs_of_one_type_sharing_a_name_count_once(self, org, secret):
        realtime_model = RealtimeModel.objects.create(name="rt-sql-dupe", org=org)
        for _ in range(2):
            RealtimeConfig.objects.create(
                custom_name="same name",
                realtime_model=realtime_model,
                org=org,
                api_key_secret=secret,
            )

        assert secret_usage_service.counts(org_id=org.id)[secret.pk] == 1

    def test_different_config_types_sharing_a_name_count_once(self, org, secret):
        """The category prefix in the key is what folds four models into one
        namespace; without it these would count as two."""
        LLMConfig.objects.create(
            custom_name="prod",
            model=LLMModel.objects.create(
                name="gpt-4o-sql-cross", llm_provider=None, org=org
            ),
            org=org,
            api_key_secret=secret,
        )
        EmbeddingConfig.objects.create(
            custom_name="prod",
            model=EmbeddingModel.objects.create(name="embed-sql-cross", org=org),
            org=org,
            api_key_secret=secret,
        )

        assert secret_usage_service.counts(org_id=org.id)[secret.pk] == 1

    def test_two_different_sources_in_one_flow_count_once(self, org, secret):
        """Cross-source, not just cross-row: a PythonNode and a ConditionalEdge are
        separate registry entries and separate union branches, so collapsing them
        relies on the key being the graph rather than the node."""
        graph = Graph.objects.create(name="Cross source flow", org=org)
        node_code = PythonCode.objects.create(code=DECLARING_CODE)
        node_code.secrets.set([secret])
        router = PythonNode.objects.create(
            graph=graph, node_name="route", python_code=node_code
        )
        edge_code = PythonCode.objects.create(code=DECLARING_CODE)
        edge_code.secrets.set([secret])
        ConditionalEdge.objects.create(
            graph=graph, source_node_id=router.pk, python_code=edge_code
        )

        assert secret_usage_service.counts(org_id=org.id)[secret.pk] == 1

    def test_a_config_and_a_tool_sharing_a_name_count_separately(self, org, secret):
        """The other direction: the prefix must not over-collapse across categories."""
        LLMConfig.objects.create(
            custom_name="shared",
            model=LLMModel.objects.create(
                name="gpt-4o-sql-sep", llm_provider=None, org=org
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

        assert secret_usage_service.counts(org_id=org.id)[secret.pk] == 2
