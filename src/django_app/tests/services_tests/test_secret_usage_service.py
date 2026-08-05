"""Aggregation: how a flat UsageHit stream becomes the two surfaces.

The load-bearing property is that counts() and summary() agree — usage_count on
the list must always equal the detail endpoint's total for the same secret, or the
table chip and the dialog headline contradict each other.
"""

import pytest

from tables.models import EmbeddingConfig, LLMConfig, McpTool, PythonCode
from tables.models.embedding_models import EmbeddingModel
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    Graph,
    PythonNode,
)
from tables.models.llm_models import LLMModel, RealtimeConfig, RealtimeModel
from tables.models.rbac_models import Organization
from tables.services.secrets import secret_service
from tables.services.secrets.usage_service import (
    SecretUsageCountProvider,
    secret_usage_service,
)

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
        for node_name in ("first", "second", "third"):
            PythonNode.objects.create(
                graph=graph,
                node_name=node_name,
                python_code=PythonCode.objects.create(code=DECLARING_CODE),
            )

        assert secret_usage_service.counts(org_id=org.id)[secret.pk] == 1

    def test_counts_sum_across_categories(self, org, secret):
        graph = Graph.objects.create(name="Counted flow", org=org)
        PythonNode.objects.create(
            graph=graph,
            node_name="node",
            python_code=PythonCode.objects.create(code=DECLARING_CODE),
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
        secret_service.create(text="sk-other", org=other, name="USAGE_KEY")
        other_graph = Graph.objects.create(name="Other flow", org=other)
        PythonNode.objects.create(
            graph=other_graph,
            node_name="other node",
            python_code=PythonCode.objects.create(code=DECLARING_CODE),
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
        PythonNode.objects.create(
            graph=graph,
            node_name="node",
            python_code=PythonCode.objects.create(code=DECLARING_CODE),
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
        ClassificationDecisionTableNode.objects.create(
            graph=graph,
            node_name="classify",
            pre_python_code=PythonCode.objects.create(code=DECLARING_CODE),
            post_python_code=PythonCode.objects.create(code=DECLARING_CODE),
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
            PythonNode.objects.create(
                graph=graph,
                node_name=node_name,
                python_code=PythonCode.objects.create(code=DECLARING_CODE),
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
        PythonNode.objects.create(
            graph=graph,
            node_name="node",
            python_code=PythonCode.objects.create(code=DECLARING_CODE),
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
        PythonNode.objects.create(
            graph=graph,
            node_name="node",
            python_code=PythonCode.objects.create(code=DECLARING_CODE),
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
class TestSecretUsageCountProvider:
    def test_computes_once_and_serves_repeated_lookups(self, org, secret):
        unused = secret_service.create(text="sk-p", org=org, name="PROVIDER_KEY")
        provider = SecretUsageCountProvider(org_id=org.id)

        assert provider.count_for(secret_id=secret.pk) == 0
        assert provider.count_for(secret_id=unused.pk) == 0
        assert provider.count_for(secret_id=secret.pk) == 0

    def test_an_unknown_secret_id_raises_rather_than_reading_as_unused(
        self, org, secret
    ):
        """counts() enumerates every secret in the org, so an absent key means the
        service is broken. Failing loudly beats rendering a broken sweep as "0"."""
        provider = SecretUsageCountProvider(org_id=org.id)

        with pytest.raises(KeyError):
            provider.count_for(secret_id=secret.pk + 10_000)
