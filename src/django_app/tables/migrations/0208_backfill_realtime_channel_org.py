# Hand-written migration — Migration B of 3 (schema -> backfill -> NOT NULL).
#
# Derives each RealtimeChannel's owning org from the FK chain, in priority
# order:
#   1. RealtimeChannel -> TwilioChannel(channel) -> webhook_trigger.org_id —
#      already NOT NULL as of 0206_webhook_trigger_org_not_null, the most
#      direct ownership signal for a channel whose Twilio webhook is
#      configured. A bare RealtimeChannel with no Twilio detail row
#      attached yet simply has no row here, and falls through to (2).
#   2. RealtimeChannel.realtime_agent.agent.org_id — the realtime agent
#      chain, for channels with no Twilio detail row (or one with no
#      webhook_trigger set / a null-org one).
#   3. Falls back to the default org (shared assign_default_org helper) for
#      any row neither chain can resolve (e.g. fully orphaned rows) or with
#      ambiguous/conflicting signals across the two chains (defensive, logs
#      a warning and picks the first org deterministically).
#
# Idempotent: only touches rows where org_id IS NULL.

from loguru import logger
from django.db import migrations

from tables.migrations._helpers import assign_default_org, resolve_default_org


def forwards(apps, schema_editor):
    RealtimeChannel = apps.get_model("tables", "RealtimeChannel")
    TwilioChannel = apps.get_model("tables", "TwilioChannel")

    unassigned_pks = list(
        RealtimeChannel.objects.filter(org_id__isnull=True).values_list(
            "pk", flat=True
        )
    )
    for channel_pk in unassigned_pks:
        realtime_channel = RealtimeChannel.objects.select_related(
            "realtime_agent__agent",
        ).get(pk=channel_pk)

        org_ids = set()

        twilio_channel = (
            TwilioChannel.objects.select_related("webhook_trigger")
            .filter(channel_id=channel_pk)
            .first()
        )
        if twilio_channel is not None:
            webhook_trigger = twilio_channel.webhook_trigger
            if webhook_trigger is not None and webhook_trigger.org_id is not None:
                org_ids.add(webhook_trigger.org_id)

        realtime_agent = realtime_channel.realtime_agent
        if realtime_agent is not None and realtime_agent.agent is not None:
            agent_org_id = realtime_agent.agent.org_id
            if agent_org_id is not None:
                org_ids.add(agent_org_id)

        if not org_ids:
            # Neither chain resolves an org (e.g. fully orphaned row) — left
            # for the generic default-org fallback below.
            continue

        if len(org_ids) > 1:
            logger.warning(
                f"RealtimeChannel pk={channel_pk} has conflicting org signals "
                f"{sorted(org_ids)} across twilio.webhook_trigger and "
                "realtime_agent chains — assigning the first one "
                "deterministically."
            )

        org_id = sorted(org_ids)[0]
        RealtimeChannel.objects.filter(pk=channel_pk).update(org_id=org_id)

    # Defensive fallback for any RealtimeChannel still without an org
    # (neither chain resolved) — same convention as other org backfills.
    default_org = resolve_default_org(apps)
    assign_default_org(apps, "tables.RealtimeChannel", default_org)


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0207_realtime_channel_org_scoped"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
