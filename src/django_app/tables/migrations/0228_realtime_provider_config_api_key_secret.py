# Closes the same gap 0220 closed for NgrokWebhookConfig/TwilioChannel:
# OpenAIRealtimeConfig/ElevenLabsRealtimeConfig/GeminiRealtimeConfig still
# stored their provider api_key (and OpenAI's transcription_api_key) as
# plaintext TextField columns instead of routing them through the Secret
# table like every other credential-bearing config (EmbeddingConfig,
# LLMConfig, NgrokWebhookConfig, TwilioChannel).
#
# Same shape as 0220: AddField (nullable FK) -> RunPython backfill (encrypt
# existing plaintext into a new Secret per row) -> RemoveField (drop the old
# plaintext column). These three models are themselves OrgScopedModel, so
# org_id/created_by_id are read directly off each instance -- no parent
# relation lookup needed.

import django.db.models.deletion
from django.db import migrations, models
from loguru import logger

from tables.services.secrets import secret_encryption


def migrate_realtime_api_keys_to_secrets(apps, schema_editor):
    Secret = apps.get_model("tables", "Secret")

    def _migrate(queryset, model_label, field_name, fk_name):
        base_name = f"{model_label}-{field_name.replace('_', '-')}"
        counts_by_org = {}
        for instance in queryset.order_by("pk"):
            raw_value = getattr(instance, field_name)
            if not raw_value:
                continue
            org_id = instance.org_id
            if org_id is None:
                logger.warning(
                    f"Skipping {model_label} pk={instance.pk}: no org set "
                    f"for {field_name}"
                )
                continue
            count = counts_by_org.get(org_id, 0) + 1
            counts_by_org[org_id] = count
            name = base_name if count == 1 else f"{base_name}-{count}"
            secret = Secret(
                org_id=org_id,
                name=name,
                created_by_id=instance.created_by_id,
            )
            secret_encryption.encrypt(text=raw_value).write_to(secret)
            secret.save()
            setattr(instance, fk_name, secret)
            instance.save(update_fields=[fk_name])

    OpenAIRealtimeConfig = apps.get_model("tables", "OpenAIRealtimeConfig")
    _migrate(
        OpenAIRealtimeConfig.objects.all(),
        "openairealtimeconfig",
        "api_key",
        "api_key_secret",
    )
    _migrate(
        OpenAIRealtimeConfig.objects.all(),
        "openairealtimeconfig",
        "transcription_api_key",
        "transcription_api_key_secret",
    )

    ElevenLabsRealtimeConfig = apps.get_model("tables", "ElevenLabsRealtimeConfig")
    _migrate(
        ElevenLabsRealtimeConfig.objects.all(),
        "elevenlabsrealtimeconfig",
        "api_key",
        "api_key_secret",
    )

    GeminiRealtimeConfig = apps.get_model("tables", "GeminiRealtimeConfig")
    _migrate(
        GeminiRealtimeConfig.objects.all(),
        "geminirealtimeconfig",
        "api_key",
        "api_key_secret",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0227_merge_20260825_1744"),
    ]

    operations = [
        migrations.AddField(
            model_name="openairealtimeconfig",
            name="api_key_secret",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="openai_realtime_configs",
                to="tables.secret",
            ),
        ),
        migrations.AddField(
            model_name="openairealtimeconfig",
            name="transcription_api_key_secret",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="openai_realtime_transcription_configs",
                to="tables.secret",
            ),
        ),
        migrations.AddField(
            model_name="elevenlabsrealtimeconfig",
            name="api_key_secret",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="elevenlabs_realtime_configs",
                to="tables.secret",
            ),
        ),
        migrations.AddField(
            model_name="geminirealtimeconfig",
            name="api_key_secret",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="gemini_realtime_configs",
                to="tables.secret",
            ),
        ),
        migrations.RunPython(
            migrate_realtime_api_keys_to_secrets,
            reverse_code=migrations.RunPython.noop,
        ),
        # The backfill's instance.save(update_fields=[fk_name]) UPDATEs rows
        # in these same tables via a newly-added FK, leaving deferred FK
        # constraint triggers pending; Postgres refuses an ALTER TABLE on a
        # table with pending trigger events in the same transaction. Force
        # them to fire now, before the RemoveField ops below.
        migrations.RunSQL(
            sql="SET CONSTRAINTS ALL IMMEDIATE;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RemoveField(
            model_name="openairealtimeconfig",
            name="api_key",
        ),
        migrations.RemoveField(
            model_name="openairealtimeconfig",
            name="transcription_api_key",
        ),
        migrations.RemoveField(
            model_name="elevenlabsrealtimeconfig",
            name="api_key",
        ),
        migrations.RemoveField(
            model_name="geminirealtimeconfig",
            name="api_key",
        ),
    ]
