"""
Migration: migrate RealtimeAgentDefinition to per-provider realtime configs

Mirrors 0168_realtime_provider_configs_and_channels.py, which performed the
identical conversion for RealtimeAgent. RealtimeAgentDefinition was added
~2 months after 0168 (in the "add realtime to agent definitions" feature) and
was never migrated off the deprecated RealtimeConfig / RealtimeTranscriptionConfig
FK pair — this migration closes that gap so both RealtimeAgent and
RealtimeAgentDefinition use the same OpenAIRealtimeConfig / ElevenLabsRealtimeConfig
/ GeminiRealtimeConfig models.

Schema changes:
- Add openai_config / elevenlabs_config / gemini_config FKs to RealtimeAgentDefinition
- Drop realtime_config / realtime_transcription_config from RealtimeAgentDefinition

Note: this migration also supersedes the now-deleted
0217_realtimeagentchat_legacy_config_snapshot.py stopgap (never applied to any
database) — that migration's AddField operations for
RealtimeAgentChat.realtime_config / realtime_transcription_config are simply
gone (file deleted), not reversed, since they never made it into any DB.
RealtimeAgentChat's existing openai_config / elevenlabs_config / gemini_config
snapshot fields — already used by the RealtimeAgent flow — are reused by the
RealtimeAgentDefinition flow instead, so the legacy pair was never needed.

Data migration:
- For each RealtimeAgentDefinition that has a realtime_config, create the
  matching provider config (or reuse one already created for an identical old
  config) and set the new FK — same provider-detection + caching approach as
  0168's migrate_realtime_agent_configs.

Reversibility: the data migration's RunPython step is one-way
(reverse_code=migrations.RunPython.noop), matching the accepted precedent in
0168. Reversing this migration restores the old FK columns but does NOT
restore the original realtime_config / realtime_transcription_config linkage
on existing rows — a rollback after this has run and been used in production
would leave RealtimeAgentDefinition rows without a realtime config until
manually reassigned.
"""

import django.db.models.deletion
from django.db import migrations, models
from loguru import logger

from tables.services.secrets import SecretDecryptionError, secret_encryption


def _provider_name(realtime_config) -> str | None:
    """Extract provider name from the old RealtimeConfig chain."""
    try:
        model = realtime_config.realtime_model
        provider = model.provider
        if provider and provider.name:
            return provider.name.lower()
    except Exception:
        pass
    return None


def _api_key(cfg) -> str:
    if hasattr(cfg, "api_key"):
        return cfg.api_key or ""

    secret = getattr(cfg, "api_key_secret", None)
    if secret is None or not secret.value:
        return ""
    try:
        return secret_encryption.decrypt(encryptedtext=secret.value)
    except SecretDecryptionError:
        logger.warning(
            f"Could not decrypt Secret pk={secret.pk} for {type(cfg).__name__} "
            f"pk={cfg.pk}; leaving the new config's api_key empty."
        )
        return ""


def migrate_realtime_agent_definition_configs(apps, schema_editor):
    """Populate new provider config tables from old RealtimeConfig data."""
    RealtimeAgentDefinition = apps.get_model("tables", "RealtimeAgentDefinition")
    OpenAIRealtimeConfig = apps.get_model("tables", "OpenAIRealtimeConfig")
    ElevenLabsRealtimeConfig = apps.get_model("tables", "ElevenLabsRealtimeConfig")
    GeminiRealtimeConfig = apps.get_model("tables", "GeminiRealtimeConfig")

    # Map old realtime_config id → new provider config object (to avoid duplicates)
    openai_cache: dict[int, object] = {}
    elevenlabs_cache: dict[int, object] = {}
    gemini_cache: dict[int, object] = {}

    for agent_definition in RealtimeAgentDefinition.objects.select_related(
        "realtime_config__realtime_model__provider",
        "realtime_transcription_config__realtime_transcription_model",
    ).all():
        rt_cfg = agent_definition.realtime_config
        if rt_cfg is None:
            continue

        provider = _provider_name(rt_cfg)
        old_cfg_id = rt_cfg.pk
        org_id = getattr(rt_cfg, "org_id", None)

        if provider == "elevenlabs":
            if old_cfg_id not in elevenlabs_cache:
                el_cfg = ElevenLabsRealtimeConfig.objects.create(
                    custom_name=rt_cfg.custom_name,
                    api_key=_api_key(rt_cfg),
                    model_name=rt_cfg.realtime_model.name,
                    language=agent_definition.language or "",
                    org_id=org_id,
                )
                elevenlabs_cache[old_cfg_id] = el_cfg
            agent_definition.elevenlabs_config = elevenlabs_cache[old_cfg_id]

        elif provider == "gemini":
            if old_cfg_id not in gemini_cache:
                g_cfg = GeminiRealtimeConfig.objects.create(
                    custom_name=rt_cfg.custom_name,
                    api_key=_api_key(rt_cfg),
                    model_name=rt_cfg.realtime_model.name,
                    voice_recognition_prompt=agent_definition.voice_recognition_prompt
                    or "",
                    org_id=org_id,
                )
                gemini_cache[old_cfg_id] = g_cfg
            agent_definition.gemini_config = gemini_cache[old_cfg_id]

        else:
            # Default: OpenAI
            if old_cfg_id not in openai_cache:
                transcription_cfg = agent_definition.realtime_transcription_config
                openai_cfg = OpenAIRealtimeConfig.objects.create(
                    custom_name=rt_cfg.custom_name,
                    api_key=_api_key(rt_cfg),
                    model_name=rt_cfg.realtime_model.name,
                    transcription_model_name=(
                        transcription_cfg.realtime_transcription_model.name
                        if transcription_cfg
                        else "whisper-1"
                    ),
                    transcription_api_key=(
                        _api_key(transcription_cfg) if transcription_cfg else ""
                    ),
                    voice_recognition_prompt=agent_definition.voice_recognition_prompt
                    or "",
                    org_id=org_id,
                )
                openai_cache[old_cfg_id] = openai_cfg
            agent_definition.openai_config = openai_cache[old_cfg_id]

        agent_definition.save(
            update_fields=["openai_config", "elevenlabs_config", "gemini_config"]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0216_webhook_trigger_org_path_unique"),
    ]

    operations = [
        # -----------------------------------------------------------------------
        # 1. Add new FK columns to RealtimeAgentDefinition
        # -----------------------------------------------------------------------
        migrations.AddField(
            model_name="realtimeagentdefinition",
            name="openai_config",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="realtime_agent_definitions",
                to="tables.openairealtimeconfig",
            ),
        ),
        migrations.AddField(
            model_name="realtimeagentdefinition",
            name="elevenlabs_config",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="realtime_agent_definitions",
                to="tables.elevenlabsrealtimeconfig",
            ),
        ),
        migrations.AddField(
            model_name="realtimeagentdefinition",
            name="gemini_config",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="realtime_agent_definitions",
                to="tables.geminirealtimeconfig",
            ),
        ),
        # -----------------------------------------------------------------------
        # 2. Data migration — convert existing realtime_config /
        #    realtime_transcription_config data into the new provider configs
        # -----------------------------------------------------------------------
        migrations.RunPython(
            migrate_realtime_agent_definition_configs,
            reverse_code=migrations.RunPython.noop,
        ),
        # -----------------------------------------------------------------------
        # 3. Remove old fields from RealtimeAgentDefinition
        # -----------------------------------------------------------------------
        migrations.RemoveField(
            model_name="realtimeagentdefinition", name="realtime_config"
        ),
        migrations.RemoveField(
            model_name="realtimeagentdefinition",
            name="realtime_transcription_config",
        ),
    ]
