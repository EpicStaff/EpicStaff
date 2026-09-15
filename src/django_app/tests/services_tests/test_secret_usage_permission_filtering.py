"""Row-level and static readability resolution for secret usage sources."""

import pytest
from django.utils import timezone

from tables.models import Organization, Secret
from tables.models.graph_models import Graph, WebhookTriggerNode
from tables.models.webhook_models import (
    NgrokWebhookConfig,
    ProviderType,
    RealtimeChannel,
    TwilioChannel,
    WebhookTrigger,
)
from tables.services.secrets import secret_service
from tables.services.secrets.usage_sources import (
    READABLE_ALWAYS,
    READABLE_NEVER,
    USAGE_SOURCES,
)

pytestmark = pytest.mark.django_db


def _ngrok_source():
    """The NgrokWebhookConfig usage source, found by model rather than position."""
    return next(
        source for source in USAGE_SOURCES if source.model is NgrokWebhookConfig
    )


def _llm_source():
    """A statically-readable source, for the non-conditional branches."""
    from tables.models import LLMConfig

    return next(source for source in USAGE_SOURCES if source.model is LLMConfig)


@pytest.fixture
def secret(default_org):
    return secret_service.create(text="ngrok-token", org=default_org, name="NGROK")


@pytest.fixture
def orphan_ngrok(default_org, secret):
    """An ngrok config whose trigger no flow node and no channel references."""
    trigger = WebhookTrigger.objects.create(
        path="orphan", provider_type=ProviderType.NGROK, org=default_org
    )
    return NgrokWebhookConfig.objects.create(
        name="orphan-cfg", trigger=trigger, auth_token_secret=secret
    )


@pytest.fixture
def referenced_ngrok(default_org, secret):
    """An ngrok config whose trigger a live flow node references."""
    trigger = WebhookTrigger.objects.create(
        path="referenced", provider_type=ProviderType.NGROK, org=default_org
    )
    config = NgrokWebhookConfig.objects.create(
        name="referenced-cfg", trigger=trigger, auth_token_secret=secret
    )
    graph = Graph.objects.create(name="g", org=default_org)
    from tables.models.python_models import PythonCode

    WebhookTriggerNode.objects.create(
        node_name="n",
        graph=graph,
        webhook_trigger=trigger,
        python_code=PythonCode.objects.create(code=""),
    )
    return config


def test_static_source_readable_when_type_held():
    source = _llm_source()

    result = source.readability(readable_types=frozenset({"llm_configs"}), org_id=1)

    assert result == READABLE_ALWAYS


def test_static_source_never_readable_without_type():
    source = _llm_source()

    result = source.readability(readable_types=frozenset({"flows"}), org_id=1)

    assert result == READABLE_NEVER


def test_webhook_source_always_readable_with_llm_configs():
    """llm_configs reaches the trigger's own endpoint, so no row check is needed."""
    source = _ngrok_source()

    result = source.readability(readable_types=frozenset({"llm_configs"}), org_id=1)

    assert result == READABLE_ALWAYS


def test_webhook_source_never_readable_without_any_path():
    source = _ngrok_source()

    result = source.readability(readable_types=frozenset({"tools"}), org_id=1)

    assert result == READABLE_NEVER


def _is_readable_map(*, source, org_id, secret_ids, readable_types):
    """usage_key -> is_readable, as the union in counts() will see it."""
    readability = source.readability(readable_types=readable_types, org_id=org_id)
    rows = source.count_pairs(
        org_id=org_id, secret_ids=secret_ids, readability=readability
    )
    return {usage_key: is_readable for _, usage_key, is_readable in rows}


def test_orphaned_trigger_is_hidden_from_flows_reader(
    default_org, secret, orphan_ngrok
):
    """No flow references it, so flows:READ grants no route to it."""
    result = _is_readable_map(
        source=_ngrok_source(),
        org_id=default_org.id,
        secret_ids={secret.pk},
        readable_types=frozenset({"flows"}),
    )

    assert result == {"channels:ngrok_webhook_config:orphan-cfg": False}


def test_referenced_trigger_is_readable_by_flows_reader(
    default_org, secret, referenced_ngrok
):
    result = _is_readable_map(
        source=_ngrok_source(),
        org_id=default_org.id,
        secret_ids={secret.pk},
        readable_types=frozenset({"flows"}),
    )

    assert result == {"channels:ngrok_webhook_config:referenced-cfg": True}


def test_soft_deleted_node_does_not_grant_visibility(
    default_org, secret, referenced_ngrok
):
    """A related join ignores the ActiveManager, so is_soft_deleted must be explicit."""
    WebhookTriggerNode.all_objects.update(
        is_soft_deleted=True, soft_deleted_at=timezone.now()
    )

    result = _is_readable_map(
        source=_ngrok_source(),
        org_id=default_org.id,
        secret_ids={secret.pk},
        readable_types=frozenset({"flows"}),
    )

    assert result == {"channels:ngrok_webhook_config:referenced-cfg": False}


def test_referencing_node_in_another_org_does_not_grant_visibility(
    default_org, secret, referenced_ngrok
):
    other = Organization.objects.create(name="other")
    Graph.objects.filter(name="g").update(org=other)

    result = _is_readable_map(
        source=_ngrok_source(),
        org_id=default_org.id,
        secret_ids={secret.pk},
        readable_types=frozenset({"flows"}),
    )

    assert result == {"channels:ngrok_webhook_config:referenced-cfg": False}


@pytest.fixture
def twilio_referenced_ngrok(default_org, secret):
    """An ngrok config whose trigger only a Twilio channel references."""
    trigger = WebhookTrigger.objects.create(
        path="voiceline", provider_type=ProviderType.NGROK, org=default_org
    )
    config = NgrokWebhookConfig.objects.create(
        name="voice-cfg", trigger=trigger, auth_token_secret=secret
    )
    channel = RealtimeChannel.objects.create(name="Voice line", org=default_org)
    TwilioChannel.objects.create(
        channel=channel,
        account_sid="AC_test",
        auth_token_secret=secret,
        webhook_trigger=trigger,
    )
    return config


def test_twilio_reference_grants_voice_but_not_flows(
    default_org, secret, twilio_referenced_ngrok
):
    """The voice conditional path is independent of the two flow paths."""
    source = _ngrok_source()
    key = "channels:ngrok_webhook_config:voice-cfg"

    with_voice = _is_readable_map(
        source=source,
        org_id=default_org.id,
        secret_ids={secret.pk},
        readable_types=frozenset({"voice"}),
    )
    with_flows = _is_readable_map(
        source=source,
        org_id=default_org.id,
        secret_ids={secret.pk},
        readable_types=frozenset({"flows"}),
    )

    assert with_voice[key] is True
    assert with_flows[key] is False


def _effective(*, readable_types):
    """An EffectivePermissions granting READ on exactly these resource types."""
    from tables.models.rbac_models.rbac_enums import Permission
    from tables.services.rbac.effective_permissions import EffectivePermissions

    return EffectivePermissions(
        is_superadmin=False,
        role=None,
        by_resource={rt: int(Permission.READ) for rt in readable_types},
    )


def test_counts_split_readable_and_hidden(default_org, secret, llm_config):
    """One readable flow-side resource and one hidden LLM config."""
    from tables.services.secrets import secret_usage_service

    llm_config.api_key_secret = secret
    llm_config.save(update_fields=["api_key_secret"])

    result = secret_usage_service.counts(
        org_id=default_org.id,
        effective=_effective(readable_types={"flows"}),
        secret_ids={secret.pk},
    )

    assert result[secret.pk].readable == 0
    assert result[secret.pk].hidden == 1


def test_superadmin_hides_nothing(default_org, secret, llm_config):
    from tables.services.rbac.effective_permissions import EffectivePermissions
    from tables.services.secrets import secret_usage_service

    llm_config.api_key_secret = secret
    llm_config.save(update_fields=["api_key_secret"])

    result = secret_usage_service.counts(
        org_id=default_org.id,
        effective=EffectivePermissions(is_superadmin=True, role=None, by_resource={}),
        secret_ids={secret.pk},
    )

    assert result[secret.pk].readable == 1
    assert result[secret.pk].hidden == 0


def test_no_readable_types_hides_everything(default_org, secret, llm_config):
    from tables.services.secrets import secret_usage_service

    llm_config.api_key_secret = secret
    llm_config.save(update_fields=["api_key_secret"])

    result = secret_usage_service.counts(
        org_id=default_org.id,
        effective=_effective(readable_types=set()),
        secret_ids={secret.pk},
    )

    assert result[secret.pk].readable == 0
    assert result[secret.pk].hidden == 1


def test_unused_secret_reports_zero_on_both(default_org, secret):
    from tables.services.secrets import secret_usage_service

    result = secret_usage_service.counts(
        org_id=default_org.id,
        effective=_effective(readable_types={"flows", "llm_configs"}),
        secret_ids={secret.pk},
    )

    assert result[secret.pk].readable == 0
    assert result[secret.pk].hidden == 0


def test_sum_equals_unfiltered_total(
    default_org, secret, llm_config, referenced_ngrok, orphan_ngrok
):
    """readable + hidden must equal the distinct-key count for every role, because the FE's delete warning is that sum."""
    from tables.services.secrets import secret_usage_service

    llm_config.api_key_secret = secret
    llm_config.save(update_fields=["api_key_secret"])

    superadmin = secret_usage_service.counts(
        org_id=default_org.id,
        effective=_effective(readable_types={"flows", "tools", "llm_configs", "voice"}),
        secret_ids={secret.pk},
    )[secret.pk]
    total = superadmin.readable + superadmin.hidden

    for readable_types in [
        set(),
        {"flows"},
        {"llm_configs"},
        {"voice"},
        {"flows", "voice"},
    ]:
        counts = secret_usage_service.counts(
            org_id=default_org.id,
            effective=_effective(readable_types=readable_types),
            secret_ids={secret.pk},
        )[secret.pk]
        assert counts.readable + counts.hidden == total, readable_types


def test_name_collision_counts_once_as_readable(default_org, secret):
    """Two ngrok configs sharing a name share one usage_key; readable wins."""
    from tables.models.python_models import PythonCode
    from tables.services.secrets import secret_usage_service

    for path, referenced in [("a", True), ("b", False)]:
        trigger = WebhookTrigger.objects.create(
            path=path, provider_type=ProviderType.NGROK, org=default_org
        )
        NgrokWebhookConfig.objects.create(
            name="shared", trigger=trigger, auth_token_secret=secret
        )
        if referenced:
            graph = Graph.objects.create(name=f"g-{path}", org=default_org)
            WebhookTriggerNode.objects.create(
                node_name="n",
                graph=graph,
                webhook_trigger=trigger,
                python_code=PythonCode.objects.create(code=""),
            )

    counts = secret_usage_service.counts(
        org_id=default_org.id,
        effective=_effective(readable_types={"flows"}),
        secret_ids={secret.pk},
    )[secret.pk]

    assert counts.readable == 1
    assert counts.hidden == 0


def test_counts_issues_one_statement(default_org, secret, llm_config):
    """The union must stay a single query after adding the boolean column."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from tables.services.secrets import secret_usage_service

    llm_config.api_key_secret = secret
    llm_config.save(update_fields=["api_key_secret"])
    effective = _effective(readable_types={"flows", "llm_configs"})

    with CaptureQueriesContext(connection) as captured:
        secret_usage_service.counts(
            org_id=default_org.id, effective=effective, secret_ids={secret.pk}
        )

    assert len(captured.captured_queries) == 1


def test_summary_omits_unreadable_categories(default_org, secret, llm_config):
    """A category the caller cannot read is absent, not present-and-empty."""
    from tables.services.secrets import secret_usage_service

    llm_config.api_key_secret = secret
    llm_config.save(update_fields=["api_key_secret"])

    result = secret_usage_service.summary(
        secret=secret, effective=_effective(readable_types={"flows"})
    )

    assert [category["key"] for category in result["categories"]] == []
    assert result["readable_total"] == 0
    assert result["hidden_total"] == 1


def test_summary_lists_readable_categories(default_org, secret, llm_config):
    from tables.services.secrets import secret_usage_service

    llm_config.api_key_secret = secret
    llm_config.save(update_fields=["api_key_secret"])

    result = secret_usage_service.summary(
        secret=secret, effective=_effective(readable_types={"llm_configs"})
    )

    assert [category["key"] for category in result["categories"]] == ["llm_configs"]
    assert result["readable_total"] == 1
    assert result["hidden_total"] == 0


def test_summary_does_not_name_an_orphaned_ngrok_to_flows_reader(
    default_org, secret, orphan_ngrok
):
    """The disclosure this design exists to prevent."""
    from tables.services.secrets import secret_usage_service

    result = secret_usage_service.summary(
        secret=secret, effective=_effective(readable_types={"flows"})
    )

    names = [
        item.get("name")
        for category in result["categories"]
        for item in category["items"]
    ]
    assert "orphan-cfg" not in names
    assert result["hidden_total"] == 1


def test_summary_readable_total_matches_counts(
    default_org, secret, llm_config, referenced_ngrok
):
    """The listed-item count and the readable key count must not drift apart."""
    from tables.services.secrets import secret_usage_service

    llm_config.api_key_secret = secret
    llm_config.save(update_fields=["api_key_secret"])
    effective = _effective(readable_types={"llm_configs", "flows"})

    summary = secret_usage_service.summary(secret=secret, effective=effective)
    counts = secret_usage_service.count_for(secret=secret, effective=effective)

    assert summary["readable_total"] == counts.readable
