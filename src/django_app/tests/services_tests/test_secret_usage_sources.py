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
    Graph,
    PythonNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.models.llm_models import (
    LLMModel,
    RealtimeModel,
    RealtimeTranscriptionModel,
)
from rbac.models import Organization
from tables.models.webhook_models import (
    NgrokWebhookConfig,
    RealtimeChannel,
    TwilioChannel,
    WebhookTrigger,
    WebhookTriggerAuth,
    WebhookTriggerAuthKind,
)
from tables.services.secrets import secret_service
from tables.services.secrets.usage_sources import (
    CATEGORY_CHANNELS,
    CATEGORY_FLOWS,
    CATEGORY_LLM_CONFIGS,
    CATEGORY_TOOLS,
    HITS_ASSEMBLERS,
    NODE_TYPE_TELEGRAM_TRIGGER,
    READABLE_ALWAYS,
    SHAPE_PROJECTIONS,
    USAGE_SOURCES,
)
from tables.services.secrets.python_code_sites import (
    NODE_TYPE_CLASSIFICATION_TABLE,
    NODE_TYPE_PYTHON,
    NODE_TYPE_WEBHOOK_TRIGGER,
)

DECLARING_CODE = 'def main(**kwargs):\n    return get_secret("USAGE_KEY")\n'


def _source(*, model, secret_path: str | None = None, node_type: str | None = None):
    """The registry's configured source for this model.

    secret_path disambiguates ClassificationDecisionTableNode, which contributes two
    entries (pre and post).
    """
    matches = [
        source
        for source in USAGE_SOURCES
        if source.model is model
        and (secret_path is None or source.secret_path == secret_path)
        and (node_type is None or source.node_type == node_type)
    ]
    assert len(matches) == 1, (
        f"expected exactly one registry source for {model.__name__}"
        f"{f' at {secret_path}' if secret_path else ''}"
        f"{f' node_type={node_type}' if node_type else ''}, found {len(matches)}"
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


def _hits(*, source, org_id, secret_ids):
    """One source's hits, assembled exactly as the service assembles its group.

    The service unions every source in a shape and assembles once; this is the
    one-source case of the same projection and the same assembler, which is what keeps
    these per-source tests honest about production behaviour. It lives here rather than
    on UsageSource because only tests look at a single source in isolation.
    """
    shape = source.detail_shape
    rows = getattr(source, SHAPE_PROJECTIONS[shape])(
        org_id=org_id, secret_ids=secret_ids, readability=READABLE_ALWAYS
    )
    return HITS_ASSEMBLERS[shape](rows=rows)


@pytest.mark.django_db
class TestForeignKeySources:
    def test_llm_config_reports_its_custom_name(self, org, secret, ids):
        model = LLMModel.objects.create(name="gpt-4o-usage", llm_provider=None, org=org)
        LLMConfig.objects.create(
            custom_name="prod cfg", model=model, org=org, api_key_secret=secret
        )

        hits = _hits(source=_source(model=LLMConfig), org_id=org.id, secret_ids=ids)

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

        assert (
            _hits(source=_source(model=LLMConfig), org_id=org.id, secret_ids=ids) == []
        )

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

        assert (
            _hits(source=_source(model=LLMConfig), org_id=org.id, secret_ids=ids) == []
        )

    def test_mcp_tool_reports_under_tools_by_name(self, org, secret, ids):
        McpTool.objects.create(
            name="search tool",
            transport="https://example.com/sse",
            tool_name="search",
            org=org,
            auth_secret=secret,
        )

        hits = _hits(source=_source(model=McpTool), org_id=org.id, secret_ids=ids)

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
                for hit in _hits(
                    source=_source(model=model), org_id=org.id, secret_ids=ids
                )
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

        hits = _hits(
            source=_source(model=TelegramTriggerNode), org_id=org.id, secret_ids=ids
        )

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
            _hits(
                source=_source(model=TelegramTriggerNode), org_id=org.id, secret_ids=ids
            )
            == []
        )


@pytest.mark.django_db
class TestChannelForeignKeySources:
    def test_twilio_channel_reports_its_parent_channel_name(self, org, secret, ids):
        channel = RealtimeChannel.objects.create(name="Support line", org=org)
        TwilioChannel.objects.create(
            channel=channel, account_sid="ACusage", auth_token_secret=secret
        )

        hits = _hits(source=_source(model=TwilioChannel), org_id=org.id, secret_ids=ids)

        assert [(hit.category, hit.resource_name) for hit in hits] == [
            (CATEGORY_CHANNELS, "Support line")
        ]

    def test_a_twilio_channel_in_another_orgs_scope_is_not_reported(
        self, org, secret, ids
    ):
        other = Organization.objects.create(name="Org SecretUsageSources Twilio Other")
        channel = RealtimeChannel.objects.create(name="Foreign line", org=other)
        TwilioChannel.objects.create(
            channel=channel, account_sid="ACforeign", auth_token_secret=secret
        )

        assert (
            _hits(source=_source(model=TwilioChannel), org_id=org.id, secret_ids=ids)
            == []
        )

    def test_ngrok_webhook_config_reports_its_own_name(self, org, secret, ids):
        trigger = WebhookTrigger.objects.create(path="usage-hook", org=org)
        NgrokWebhookConfig.objects.create(
            name="usage tunnel", trigger=trigger, auth_token_secret=secret
        )

        hits = _hits(
            source=_source(model=NgrokWebhookConfig), org_id=org.id, secret_ids=ids
        )

        assert [(hit.category, hit.resource_name) for hit in hits] == [
            (CATEGORY_CHANNELS, "usage tunnel")
        ]

    def test_an_ngrok_config_in_another_orgs_scope_is_not_reported(
        self, org, secret, ids
    ):
        other = Organization.objects.create(name="Org SecretUsageSources Ngrok Other")
        trigger = WebhookTrigger.objects.create(path="foreign-hook", org=other)
        NgrokWebhookConfig.objects.create(
            name="foreign tunnel", trigger=trigger, auth_token_secret=secret
        )

        assert (
            _hits(
                source=_source(model=NgrokWebhookConfig), org_id=org.id, secret_ids=ids
            )
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

        hits = _hits(source=_source(model=PythonNode), org_id=org.id, secret_ids=ids)

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

        assert (
            _hits(source=_source(model=PythonNode), org_id=org.id, secret_ids=ids) == []
        )

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
            len(_hits(source=_source(model=PythonNode), org_id=org.id, secret_ids=ids))
            == 1
        )

    def test_webhook_trigger_node_is_reported(self, org, secret, ids):
        graph = Graph.objects.create(name="Webhook flow", org=org)
        python_code = PythonCode.objects.create(code=DECLARING_CODE)
        python_code.secrets.set([secret])
        WebhookTriggerNode.objects.create(
            graph=graph, node_name="on_hook", python_code=python_code
        )

        hits = _hits(
            source=_source(model=WebhookTriggerNode), org_id=org.id, secret_ids=ids
        )

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

        assert len(_hits(source=pre, org_id=org.id, secret_ids=ids)) == 1
        assert len(_hits(source=post, org_id=org.id, secret_ids=ids)) == 1
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

        assert _hits(source=pre, org_id=org.id, secret_ids=ids) == []


@pytest.mark.django_db
class TestWebhookTriggerAuthSources:
    """`WebhookTriggerAuth` attaches to the `WebhookTrigger`, one row per
    trigger regardless of `kind` -- a single registry entry covers all three
    kinds (webhook/telegram/twilio)."""

    def test_attached_row_reports_its_trigger_path(self, org, secret, ids):
        trigger = WebhookTrigger.objects.create(
            path="usage-source-path", provider_type=None, org=org
        )
        WebhookTriggerAuth.objects.create(
            trigger=trigger,
            kind=WebhookTriggerAuthKind.WEBHOOK,
            secret=secret,
        )

        hits = _hits(
            source=_source(model=WebhookTriggerAuth), org_id=org.id, secret_ids=ids
        )

        assert [(hit.category, hit.resource_name) for hit in hits] == [
            (CATEGORY_CHANNELS, "usage-source-path")
        ]

    def test_a_trigger_in_another_orgs_scope_is_not_reported(self, org, secret, ids):
        other = Organization.objects.create(name="Org WebhookTriggerAuth Other")
        trigger = WebhookTrigger.objects.create(
            path="foreign-usage-source-path", provider_type=None, org=other
        )
        WebhookTriggerAuth.objects.create(
            trigger=trigger,
            kind=WebhookTriggerAuthKind.TELEGRAM,
            secret=secret,
        )

        assert (
            _hits(
                source=_source(model=WebhookTriggerAuth),
                org_id=org.id,
                secret_ids=ids,
            )
            == []
        )


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

        hits = _hits(
            source=_source(model=PythonCodeTool), org_id=org.id, secret_ids=ids
        )

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

        hits = _hits(
            source=_source(model=PythonCodeTool), org_id=org.id, secret_ids=ids
        )

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
            _hits(source=_source(model=PythonCodeTool), org_id=org.id, secret_ids=ids)
            == []
        )


@pytest.mark.django_db
def test_every_source_declares_readable_resource_types():
    """A source registered without a visibility decision is a bug, not a default."""
    from tables.services.secrets.usage_sources import USAGE_SOURCES

    missing = [
        source.model.__name__
        for source in USAGE_SOURCES
        if not source.rbac_resource_types
    ]
    assert missing == []
