# Hand-written data migration.
# Backfills provider_type on WebhookTrigger rows based on which FK is set.
# Forwards: ngrok_webhook_config_id → "ngrok", localhost_webhook_config_id → "localhost"
# Backwards: clears all provider_type values.

from django.db import migrations


def forwards(apps, schema_editor):
    WebhookTrigger = apps.get_model("tables", "WebhookTrigger")

    triggers_to_update = []
    for trigger in WebhookTrigger.objects.all():
        if trigger.ngrok_webhook_config_id is not None:
            trigger.provider_type = "ngrok"
            triggers_to_update.append(trigger)
        elif trigger.localhost_webhook_config_id is not None:
            trigger.provider_type = "localhost"
            triggers_to_update.append(trigger)
        # triggers with both FKs null: leave provider_type as null

    if triggers_to_update:
        WebhookTrigger.objects.bulk_update(triggers_to_update, ["provider_type"])


def backwards(apps, schema_editor):
    WebhookTrigger = apps.get_model("tables", "WebhookTrigger")
    WebhookTrigger.objects.all().update(provider_type=None)


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0183_add_provider_type_to_webhook_trigger"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=backwards),
    ]
