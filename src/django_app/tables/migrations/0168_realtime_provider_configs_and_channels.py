"""
Migration: per-provider realtime configs + channel architecture

Schema changes:
- Create OpenAIRealtimeConfig, ElevenLabsRealtimeConfig, GeminiRealtimeConfig
- Create RealtimeChannel, TwilioChannel
- Create ConversationRecording
- Update RealtimeAgent: add provider config FKs; drop language, voice_recognition_prompt,
  realtime_config, realtime_transcription_config
- Update RealtimeAgentChat: add provider config FKs + metadata; drop old FKs
- Update DefaultRealtimeAgentConfig: drop old fields

Data migration:
- For each RealtimeAgent that has a realtime_config, create the matching provider config
  and set the new FK.
- For each RealtimeAgentChat, set the matching provider config FK.
- Migrate VoiceSettings singleton → RealtimeChannel + TwilioChannel if populated.
"""

import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


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


def migrate_realtime_agent_configs(apps, schema_editor):
    """Populate new provider config tables from old RealtimeConfig data."""
    RealtimeAgent = apps.get_model("tables", "RealtimeAgent")
    RealtimeAgentChat = apps.get_model("tables", "RealtimeAgentChat")
    OpenAIRealtimeConfig = apps.get_model("tables", "OpenAIRealtimeConfig")
    ElevenLabsRealtimeConfig = apps.get_model("tables", "ElevenLabsRealtimeConfig")
    GeminiRealtimeConfig = apps.get_model("tables", "GeminiRealtimeConfig")

    # Map old realtime_config id → new provider config object (to avoid duplicates)
    openai_cache: dict[int, object] = {}
    elevenlabs_cache: dict[int, object] = {}
    gemini_cache: dict[int, object] = {}

    for agent in RealtimeAgent.objects.select_related(
        "realtime_config__realtime_model__provider",
        "realtime_transcription_config__realtime_transcription_model",
    ).all():
        rt_cfg = agent.realtime_config
        if rt_cfg is None:
            continue

        provider = _provider_name(rt_cfg)
        old_cfg_id = rt_cfg.pk

        if provider == "elevenlabs":
            if old_cfg_id not in elevenlabs_cache:
                el_cfg = ElevenLabsRealtimeConfig.objects.create(
                    custom_name=rt_cfg.custom_name,
                    api_key=rt_cfg.api_key or "",
                    model_name=rt_cfg.realtime_model.name,
                    language=agent.language or "",
                )
                elevenlabs_cache[old_cfg_id] = el_cfg
            agent.elevenlabs_config = elevenlabs_cache[old_cfg_id]

        elif provider == "gemini":
            if old_cfg_id not in gemini_cache:
                g_cfg = GeminiRealtimeConfig.objects.create(
                    custom_name=rt_cfg.custom_name,
                    api_key=rt_cfg.api_key or "",
                    model_name=rt_cfg.realtime_model.name,
                    voice_recognition_prompt=agent.voice_recognition_prompt or "",
                )
                gemini_cache[old_cfg_id] = g_cfg
            agent.gemini_config = gemini_cache[old_cfg_id]

        else:
            # Default: OpenAI
            if old_cfg_id not in openai_cache:
                transcription_cfg = agent.realtime_transcription_config
                openai_cfg = OpenAIRealtimeConfig.objects.create(
                    custom_name=rt_cfg.custom_name,
                    api_key=rt_cfg.api_key or "",
                    model_name=rt_cfg.realtime_model.name,
                    transcription_model_name=(
                        transcription_cfg.realtime_transcription_model.name
                        if transcription_cfg
                        else "whisper-1"
                    ),
                    transcription_api_key=(
                        transcription_cfg.api_key if transcription_cfg else ""
                    ),
                    voice_recognition_prompt=agent.voice_recognition_prompt or "",
                )
                openai_cache[old_cfg_id] = openai_cfg
            agent.openai_config = openai_cache[old_cfg_id]

        agent.save(update_fields=[
            "openai_config", "elevenlabs_config", "gemini_config"
        ])

    # Now migrate RealtimeAgentChat sessions — look up by the old FK ids
    for chat in RealtimeAgentChat.objects.select_related(
        "realtime_config__realtime_model__provider",
    ).all():
        rt_cfg = chat.realtime_config
        if rt_cfg is None:
            continue

        old_cfg_id = rt_cfg.pk
        provider = _provider_name(rt_cfg)

        if provider == "elevenlabs" and old_cfg_id in elevenlabs_cache:
            chat.elevenlabs_config = elevenlabs_cache[old_cfg_id]
        elif provider == "gemini" and old_cfg_id in gemini_cache:
            chat.gemini_config = gemini_cache[old_cfg_id]
        elif old_cfg_id in openai_cache:
            chat.openai_config = openai_cache[old_cfg_id]

        chat.save(update_fields=["openai_config", "elevenlabs_config", "gemini_config"])


def migrate_voice_settings(apps, schema_editor):
    """Convert the global VoiceSettings singleton → RealtimeChannel + TwilioChannel."""
    try:
        VoiceSettings = apps.get_model("tables", "VoiceSettings")
        RealtimeChannel = apps.get_model("tables", "RealtimeChannel")
        TwilioChannel = apps.get_model("tables", "TwilioChannel")

        vs = VoiceSettings.objects.filter(pk=1).first()
        if vs is None:
            return
        if not vs.twilio_account_sid and not vs.voice_agent_id:
            return

        channel = RealtimeChannel.objects.create(
            name="Default Twilio Channel (migrated)",
            channel_type="twilio",
            token=uuid.uuid4(),
            realtime_agent_id=vs.voice_agent_id,
            is_active=True,
        )
        TwilioChannel.objects.create(
            channel=channel,
            account_sid=vs.twilio_account_sid or "",
            auth_token=vs.twilio_auth_token or "",
            ngrok_config=vs.ngrok_config,
        )
    except Exception:
        # VoiceSettings might not have data; non-fatal
        pass


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0167_merge_20260410_1240"),
    ]

    operations = [
        # -----------------------------------------------------------------------
        # 1. Create provider-specific config tables
        # -----------------------------------------------------------------------
        migrations.CreateModel(
            name="OpenAIRealtimeConfig",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("custom_name", models.CharField(max_length=250)),
                ("api_key", models.TextField(blank=True, null=True)),
                ("model_name", models.CharField(default="gpt-4o-realtime-preview", max_length=250)),
                ("transcription_model_name", models.CharField(blank=True, default="whisper-1", max_length=250, null=True)),
                ("transcription_api_key", models.TextField(blank=True, null=True)),
                ("input_audio_format", models.CharField(
                    choices=[("pcm16", "PCM 16-bit"), ("g711_ulaw", "G.711 u-law"), ("g711_alaw", "G.711 a-law")],
                    default="pcm16", max_length=20,
                )),
                ("output_audio_format", models.CharField(
                    choices=[("pcm16", "PCM 16-bit"), ("g711_ulaw", "G.711 u-law"), ("g711_alaw", "G.711 a-law")],
                    default="pcm16", max_length=20,
                )),
                ("voice_recognition_prompt", models.TextField(blank=True, null=True)),
            ],
            options={"db_table": "openai_realtime_config"},
        ),
        migrations.CreateModel(
            name="ElevenLabsRealtimeConfig",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("custom_name", models.CharField(max_length=250)),
                ("api_key", models.TextField(blank=True, null=True)),
                ("model_name", models.CharField(default="eleven_turbo_v2_5", max_length=250)),
                ("language", models.CharField(
                    blank=True, help_text="ISO-639-1 language code, e.g. 'en'",
                    max_length=10, null=True,
                )),
            ],
            options={"db_table": "elevenlabs_realtime_config"},
        ),
        migrations.CreateModel(
            name="GeminiRealtimeConfig",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("custom_name", models.CharField(max_length=250)),
                ("api_key", models.TextField(blank=True, null=True)),
                ("model_name", models.CharField(default="gemini-2.0-flash-live-001", max_length=250)),
                ("voice_recognition_prompt", models.TextField(blank=True, null=True)),
            ],
            options={"db_table": "gemini_realtime_config"},
        ),

        # -----------------------------------------------------------------------
        # 2. Create RealtimeChannel + TwilioChannel
        # -----------------------------------------------------------------------
        migrations.CreateModel(
            name="RealtimeChannel",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=250)),
                ("channel_type", models.CharField(
                    choices=[("twilio", "Twilio")],
                    default="twilio", max_length=50,
                )),
                ("token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("realtime_agent", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="channels",
                    to="tables.realtimeagent",
                )),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"db_table": "realtime_channel"},
        ),
        migrations.CreateModel(
            name="TwilioChannel",
            fields=[
                ("channel", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    primary_key=True,
                    related_name="twilio",
                    serialize=False,
                    to="tables.realtimechannel",
                )),
                ("account_sid", models.CharField(max_length=255)),
                ("auth_token", models.CharField(max_length=255)),
                ("phone_number", models.CharField(
                    blank=True, help_text="E.164 format, e.g. +15551234567",
                    max_length=50, null=True, unique=True,
                )),
                ("ngrok_config", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to="tables.ngrokwebhookconfig",
                )),
            ],
            options={"db_table": "twilio_channel"},
        ),

        # -----------------------------------------------------------------------
        # 3. Add new FK columns to RealtimeAgent
        # -----------------------------------------------------------------------
        migrations.AddField(
            model_name="realtimeagent",
            name="openai_config",
            field=models.ForeignKey(
                blank=True, default=None, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="realtime_agents",
                to="tables.openairealtimeconfig",
            ),
        ),
        migrations.AddField(
            model_name="realtimeagent",
            name="elevenlabs_config",
            field=models.ForeignKey(
                blank=True, default=None, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="realtime_agents",
                to="tables.elevenlabsrealtimeconfig",
            ),
        ),
        migrations.AddField(
            model_name="realtimeagent",
            name="gemini_config",
            field=models.ForeignKey(
                blank=True, default=None, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="realtime_agents",
                to="tables.geminirealtimeconfig",
            ),
        ),

        # -----------------------------------------------------------------------
        # 4. Add new FK columns + metadata to RealtimeAgentChat
        # -----------------------------------------------------------------------
        migrations.AddField(
            model_name="realtimeagentchat",
            name="openai_config",
            field=models.ForeignKey(
                blank=True, default=None, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="tables.openairealtimeconfig",
            ),
        ),
        migrations.AddField(
            model_name="realtimeagentchat",
            name="elevenlabs_config",
            field=models.ForeignKey(
                blank=True, default=None, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="tables.elevenlabsrealtimeconfig",
            ),
        ),
        migrations.AddField(
            model_name="realtimeagentchat",
            name="gemini_config",
            field=models.ForeignKey(
                blank=True, default=None, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="tables.geminirealtimeconfig",
            ),
        ),
        migrations.AddField(
            model_name="realtimeagentchat",
            name="ended_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="realtimeagentchat",
            name="duration_seconds",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="realtimeagentchat",
            name="end_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("completed", "Completed"),
                    ("error", "Error"),
                    ("cancelled", "Cancelled"),
                    ("timeout", "Timeout"),
                ],
                max_length=20,
                null=True,
            ),
        ),

        # -----------------------------------------------------------------------
        # 5. Data migration
        # -----------------------------------------------------------------------
        migrations.RunPython(
            migrate_realtime_agent_configs,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RunPython(
            migrate_voice_settings,
            reverse_code=migrations.RunPython.noop,
        ),

        # -----------------------------------------------------------------------
        # 6. Remove old fields from RealtimeAgent
        # -----------------------------------------------------------------------
        migrations.RemoveField(model_name="realtimeagent", name="language"),
        migrations.RemoveField(model_name="realtimeagent", name="voice_recognition_prompt"),
        migrations.RemoveField(model_name="realtimeagent", name="realtime_config"),
        migrations.RemoveField(model_name="realtimeagent", name="realtime_transcription_config"),

        # -----------------------------------------------------------------------
        # 7. Remove old fields from RealtimeAgentChat
        # -----------------------------------------------------------------------
        migrations.RemoveField(model_name="realtimeagentchat", name="realtime_config"),
        migrations.RemoveField(model_name="realtimeagentchat", name="realtime_transcription_config"),

        # -----------------------------------------------------------------------
        # 8. Remove old fields from DefaultRealtimeAgentConfig
        # -----------------------------------------------------------------------
        migrations.RemoveField(model_name="defaultrealtimeagentconfig", name="language"),
        migrations.RemoveField(model_name="defaultrealtimeagentconfig", name="voice_recognition_prompt"),
        migrations.RemoveField(model_name="defaultrealtimeagentconfig", name="realtime_config"),
        migrations.RemoveField(model_name="defaultrealtimeagentconfig", name="realtime_transcription_config"),

        # -----------------------------------------------------------------------
        # 9. Create ConversationRecording
        # -----------------------------------------------------------------------
        migrations.CreateModel(
            name="ConversationRecording",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("rt_agent_chat", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="recordings",
                    to="tables.realtimeagentchat",
                )),
                ("file", models.FileField(upload_to="recordings/%Y/%m/%d/")),
                ("recording_type", models.CharField(
                    choices=[("inbound", "Inbound (user audio)"), ("outbound", "Outbound (agent audio)")],
                    max_length=20,
                )),
                ("audio_format", models.CharField(default="wav", max_length=10)),
                ("duration_seconds", models.FloatField(blank=True, null=True)),
                ("file_size", models.PositiveIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "conversation_recording"},
        ),

        # -----------------------------------------------------------------------
        # 10. Alter voice field default on RealtimeAgent/Chat (VoiceChoices → plain str)
        # -----------------------------------------------------------------------
        migrations.AlterField(
            model_name="realtimeagent",
            name="voice",
            field=models.CharField(default="alloy", max_length=100),
        ),
        migrations.AlterField(
            model_name="realtimeagentchat",
            name="voice",
            field=models.CharField(default="alloy", max_length=100),
        ),
        migrations.AlterField(
            model_name="defaultrealtimeagentconfig",
            name="voice",
            field=models.CharField(default="alloy", max_length=100),
        ),

        # -----------------------------------------------------------------------
        # 11. Widen language field on RealtimeAgentChat (2 → 10 chars for BCP-47)
        # -----------------------------------------------------------------------
        migrations.AlterField(
            model_name="realtimeagentchat",
            name="language",
            field=models.CharField(
                blank=True,
                help_text="ElevenLabs: ISO-639-1 language code",
                max_length=10,
                null=True,
            ),
        ),
    ]
