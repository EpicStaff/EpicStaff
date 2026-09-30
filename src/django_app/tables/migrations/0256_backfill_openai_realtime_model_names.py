from django.db import migrations


def forwards(apps, schema_editor):
    """
    Backfill OpenAIRealtimeConfig rows where model_name is one of the deprecated
    preview model names. Update both gpt-4o-realtime-preview-2024-12-17 and
    gpt-4o-mini-realtime-preview-2024-12-17 to gpt-realtime-1.5.
    """
    OpenAIRealtimeConfig = apps.get_model("tables", "OpenAIRealtimeConfig")
    OpenAIRealtimeConfig.objects.filter(
        model_name__in=[
            "gpt-4o-realtime-preview-2024-12-17",
            "gpt-4o-mini-realtime-preview-2024-12-17",
        ]
    ).update(model_name="gpt-realtime-1.5")


def backwards(apps, schema_editor):
    """
    Reverse: restore gpt-realtime-1.5 rows to the original preview model name.
    Since both preview variants map to the same new model, we restore to the
    gpt-4o variant (full-sized model). This is acceptable because reversing a
    migration typically means reverting multiple migrations at once.
    """
    OpenAIRealtimeConfig = apps.get_model("tables", "OpenAIRealtimeConfig")
    OpenAIRealtimeConfig.objects.filter(
        model_name="gpt-realtime-1.5"
    ).update(model_name="gpt-4o-realtime-preview-2024-12-17")


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0255_key_value_tables"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
