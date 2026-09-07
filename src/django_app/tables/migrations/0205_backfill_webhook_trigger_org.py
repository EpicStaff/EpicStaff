# Hand-written migration — Migration B of 3 (schema -> backfill -> NOT NULL).
#
# Derives each WebhookTrigger's owning org from whichever WebhookTriggerNode /
# TelegramTriggerNode currently references it via graph.org_id — a trigger
# already "belongs" to whichever org's node points at it today. Falls back to
# the default org (via the shared assign_default_org helper) for triggers with
# no node references at all (e.g. one only used by a TwilioChannel, or an
# orphan) or with node references spanning more than one org (defensive,
# logs a warning and picks the first org deterministically).
#
# Idempotent: only touches rows where org_id IS NULL.

from loguru import logger
from django.db import migrations

from tables.migrations._helpers import assign_default_org, resolve_default_org


def forwards(apps, schema_editor):
    WebhookTrigger = apps.get_model("tables", "WebhookTrigger")
    WebhookTriggerNode = apps.get_model("tables", "WebhookTriggerNode")
    TelegramTriggerNode = apps.get_model("tables", "TelegramTriggerNode")

    unassigned_ids = list(
        WebhookTrigger.objects.filter(org_id__isnull=True).values_list(
            "pk", flat=True
        )
    )
    for trigger_id in unassigned_ids:
        org_ids = set(
            WebhookTriggerNode.objects.filter(
                webhook_trigger_id=trigger_id, graph__org_id__isnull=False
            ).values_list("graph__org_id", flat=True)
        )
        org_ids |= set(
            TelegramTriggerNode.objects.filter(
                webhook_trigger_id=trigger_id, graph__org_id__isnull=False
            ).values_list("graph__org_id", flat=True)
        )

        if not org_ids:
            # No node reference at all (e.g. Twilio-only or orphan trigger) —
            # left for the generic default-org fallback below.
            continue

        if len(org_ids) > 1:
            logger.warning(
                f"WebhookTrigger id={trigger_id} is referenced by trigger nodes "
                f"spanning multiple orgs {sorted(org_ids)} — assigning the first "
                "one deterministically."
            )

        org_id = sorted(org_ids)[0]
        WebhookTrigger.objects.filter(pk=trigger_id).update(org_id=org_id)

    # Defensive fallback for any WebhookTrigger still without an org (no node
    # reference of either type) — same convention as other org backfills.
    default_org = resolve_default_org(apps)
    assign_default_org(apps, "tables.WebhookTrigger", default_org)


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0204_webhook_trigger_org_scoped"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
