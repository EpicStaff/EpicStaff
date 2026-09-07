# Hand-written migration — Migration C, part 1.
# Adds nullable trigger OneToOneField to NgrokWebhookConfig and LocalhostWebhookConfig,
# then backfills trigger_id from the existing FKs on WebhookTrigger.
# One NgrokWebhookConfig can be referenced by multiple triggers; the data migration
# keeps the first trigger on the existing config record and creates copies for the rest.

from django.db import migrations, models
import django.db.models.deletion


def forwards(apps, schema_editor):
    NgrokWebhookConfig = apps.get_model("tables", "NgrokWebhookConfig")
    LocalhostWebhookConfig = apps.get_model("tables", "LocalhostWebhookConfig")
    WebhookTrigger = apps.get_model("tables", "WebhookTrigger")

    # For each NgrokWebhookConfig, find all triggers that reference it
    for config in NgrokWebhookConfig.objects.all():
        triggers = list(WebhookTrigger.objects.filter(ngrok_webhook_config_id=config.pk))
        if not triggers:
            continue  # unreferenced config, skip
        # First trigger keeps the existing config record
        first_trigger = triggers[0]
        config.trigger_id = first_trigger.pk
        config.save(update_fields=["trigger_id"])
        # Remaining triggers get copies of the config
        for trigger in triggers[1:]:
            NgrokWebhookConfig.objects.create(
                trigger_id=trigger.pk,
                name=config.name,
                auth_token=config.auth_token,
                domain=config.domain,
                region=config.region,
            )

    # Same for LocalhostWebhookConfig
    for config in LocalhostWebhookConfig.objects.all():
        triggers = list(WebhookTrigger.objects.filter(localhost_webhook_config_id=config.pk))
        if not triggers:
            continue
        first_trigger = triggers[0]
        config.trigger_id = first_trigger.pk
        config.save(update_fields=["trigger_id"])
        for trigger in triggers[1:]:
            LocalhostWebhookConfig.objects.create(
                trigger_id=trigger.pk,
                name=config.name,
                domain=config.domain,
            )


def backwards(apps, schema_editor):
    NgrokWebhookConfig = apps.get_model("tables", "NgrokWebhookConfig")
    LocalhostWebhookConfig = apps.get_model("tables", "LocalhostWebhookConfig")
    NgrokWebhookConfig.objects.all().update(trigger_id=None)
    LocalhostWebhookConfig.objects.all().update(trigger_id=None)


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0184_backfill_webhook_trigger_provider_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="ngrokwebhookconfig",
            name="trigger",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="ngrok",
                to="tables.webhooktrigger",
            ),
        ),
        migrations.AddField(
            model_name="localhostwebhookconfig",
            name="trigger",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="localhost",
                to="tables.webhooktrigger",
            ),
        ),
        migrations.RunPython(forwards, reverse_code=backwards),
    ]
