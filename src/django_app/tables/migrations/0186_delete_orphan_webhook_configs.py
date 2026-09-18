# Hand-written migration — Migration C, part 2 of 3.
# Deletes NgrokWebhookConfig and LocalhostWebhookConfig rows that were not assigned
# a trigger in 0185 (configs that had no referencing WebhookTrigger at all).
# Must be a separate committed migration before 0187 enforces non-null on trigger_id,
# to avoid the PostgreSQL "pending trigger events" error when SET CONSTRAINTS is
# called within the same transaction as a DELETE on a FK-referenced table.

from django.db import migrations


def delete_orphan_configs(apps, schema_editor):
    NgrokWebhookConfig = apps.get_model("tables", "NgrokWebhookConfig")
    LocalhostWebhookConfig = apps.get_model("tables", "LocalhostWebhookConfig")
    NgrokWebhookConfig.objects.filter(trigger_id__isnull=True).delete()
    LocalhostWebhookConfig.objects.filter(trigger_id__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0185_add_trigger_onetone_to_webhook_configs"),
    ]

    operations = [
        migrations.RunPython(delete_orphan_configs, reverse_code=migrations.RunPython.noop),
    ]
