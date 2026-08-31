# Hand-written migration — Migration B of 3 (schema -> backfill -> NOT NULL),
# same pattern as 0207/0208/0209 for RealtimeChannel.
#
# Derives each provider config's owning org from the single reverse FK chain
# available: <ProviderConfig>.realtime_agents (RealtimeAgent.<provider>_config)
# -> RealtimeAgent.agent.org_id. A config can be referenced by at most one
# RealtimeAgent in practice (the "exactly one provider config" invariant is
# enforced on RealtimeAgent.clean(), not by a DB constraint here), but a
# config could in theory be attached to zero RealtimeAgents (created but
# never assigned) — those fall through to the default-org fallback below.
#
# Idempotent: only touches rows where org_id IS NULL.

from loguru import logger
from django.db import migrations

from tables.migrations._helpers import assign_default_org, resolve_default_org


def _backfill_from_realtime_agents(model, model_label, apps):
    unassigned_pks = list(
        model.objects.filter(org_id__isnull=True).values_list("pk", flat=True)
    )
    for pk in unassigned_pks:
        config = model.objects.get(pk=pk)

        org_ids = set()
        for realtime_agent in config.realtime_agents.select_related("agent").all():
            if realtime_agent.agent is not None and realtime_agent.agent.org_id is not None:
                org_ids.add(realtime_agent.agent.org_id)

        if not org_ids:
            # No referencing RealtimeAgent (or none with a resolvable org) —
            # left for the generic default-org fallback below.
            continue

        if len(org_ids) > 1:
            logger.warning(
                f"{model_label} pk={pk} has conflicting org signals "
                f"{sorted(org_ids)} across its referencing RealtimeAgents — "
                "assigning the first one deterministically."
            )

        org_id = sorted(org_ids)[0]
        model.objects.filter(pk=pk).update(org_id=org_id)


def forwards(apps, schema_editor):
    OpenAIRealtimeConfig = apps.get_model("tables", "OpenAIRealtimeConfig")
    ElevenLabsRealtimeConfig = apps.get_model("tables", "ElevenLabsRealtimeConfig")
    GeminiRealtimeConfig = apps.get_model("tables", "GeminiRealtimeConfig")

    _backfill_from_realtime_agents(
        OpenAIRealtimeConfig, "tables.OpenAIRealtimeConfig", apps
    )
    _backfill_from_realtime_agents(
        ElevenLabsRealtimeConfig, "tables.ElevenLabsRealtimeConfig", apps
    )
    _backfill_from_realtime_agents(
        GeminiRealtimeConfig, "tables.GeminiRealtimeConfig", apps
    )

    # Defensive fallback for any config still without an org (no referencing
    # RealtimeAgent resolved one) — same convention as other org backfills.
    default_org = resolve_default_org(apps)
    assign_default_org(apps, "tables.OpenAIRealtimeConfig", default_org)
    assign_default_org(apps, "tables.ElevenLabsRealtimeConfig", default_org)
    assign_default_org(apps, "tables.GeminiRealtimeConfig", default_org)


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0212_realtime_provider_configs_org_scoped"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
