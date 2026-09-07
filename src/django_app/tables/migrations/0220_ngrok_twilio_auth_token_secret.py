# Manually written to close a gap left by the 0208-0219 secrets-management
# merge: NgrokWebhookConfig.auth_token_secret / TwilioChannel.auth_token_secret
# already exist on the model classes (hand-authored ahead of the migration,
# mirroring the FK-secret pattern from 0210_embeddingconfig_api_key_secret_and_more.py),
# but no migration had ever added the column or backfilled existing plaintext
# `auth_token` values into `Secret` rows. Without this migration the DB schema
# still carries the old plaintext `auth_token` CharField and Django's model
# state is out of sync with it (`NgrokWebhookConfig(auth_token=...)` /
# `TwilioChannel(auth_token=...)` raise `TypeError` against the current model).
#
# Same shape as 0210: AddField (nullable FK) -> RunPython backfill (encrypt
# existing plaintext into a new Secret per row, org resolved via the parent
# relation) -> RemoveField (drop the old plaintext column). This is NOT a
# schema-only change — see migrate_sensitive_fields_to_secrets below.

import django.db.models.deletion
from django.db import migrations, models
from loguru import logger

from tables.services.secrets import secret_encryption


def migrate_sensitive_fields_to_secrets(apps, schema_editor):
    Secret = apps.get_model("tables", "Secret")

    def _migrate(
        queryset,
        model_label,
        field_name,
        fk_name,
        org_id_getter,
        created_by_id_getter,
    ):
        base_name = f"{model_label}-{field_name.replace('_', '-')}"
        counts_by_org = {}
        for instance in queryset.order_by("pk"):
            raw_value = getattr(instance, field_name)
            if not raw_value:
                continue
            org_id = org_id_getter(instance)
            if org_id is None:
                logger.warning(
                    f"Skipping {model_label} pk={instance.pk}: no resolvable "
                    f"org for {field_name}"
                )
                continue
            count = counts_by_org.get(org_id, 0) + 1
            counts_by_org[org_id] = count
            name = base_name if count == 1 else f"{base_name}-{count}"
            secret = Secret(
                org_id=org_id,
                name=name,
                created_by_id=created_by_id_getter(instance),
            )
            secret_encryption.encrypt(text=raw_value).write_to(secret)
            secret.save()
            setattr(instance, fk_name, secret)
            instance.save(update_fields=[fk_name])

    WebhookTrigger = apps.get_model("tables", "WebhookTrigger")
    RealtimeChannel = apps.get_model("tables", "RealtimeChannel")

    def _trigger_org_id(instance):
        trigger = WebhookTrigger.objects.filter(pk=instance.trigger_id).first()
        return trigger.org_id if trigger else None

    def _trigger_created_by_id(instance):
        trigger = WebhookTrigger.objects.filter(pk=instance.trigger_id).first()
        return trigger.created_by_id if trigger else None

    NgrokWebhookConfig = apps.get_model("tables", "NgrokWebhookConfig")
    _migrate(
        NgrokWebhookConfig.objects.all(),
        "ngrokwebhookconfig",
        "auth_token",
        "auth_token_secret",
        _trigger_org_id,
        _trigger_created_by_id,
    )

    def _channel_org_id(instance):
        channel = RealtimeChannel.objects.filter(pk=instance.channel_id).first()
        return channel.org_id if channel else None

    def _channel_created_by_id(instance):
        channel = RealtimeChannel.objects.filter(pk=instance.channel_id).first()
        return channel.created_by_id if channel else None

    TwilioChannel = apps.get_model("tables", "TwilioChannel")
    _migrate(
        TwilioChannel.objects.all(),
        "twiliochannel",
        "auth_token",
        "auth_token_secret",
        _channel_org_id,
        _channel_created_by_id,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0219_merge_20260820_1545"),
    ]

    operations = [
        migrations.AddField(
            model_name="ngrokwebhookconfig",
            name="auth_token_secret",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="ngrok_webhook_configs",
                to="tables.secret",
            ),
        ),
        migrations.AddField(
            model_name="twiliochannel",
            name="auth_token_secret",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="twilio_channels",
                to="tables.secret",
            ),
        ),
        migrations.RunPython(
            migrate_sensitive_fields_to_secrets,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name="ngrokwebhookconfig",
            name="auth_token",
        ),
        migrations.RemoveField(
            model_name="twiliochannel",
            name="auth_token",
        ),
    ]
