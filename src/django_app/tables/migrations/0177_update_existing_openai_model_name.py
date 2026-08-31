from django.db import migrations

def forwards(apps, schema_editor):
    OpenAIRealtimeConfig = apps.get_model("tables", "OpenAIRealtimeConfig")
    OpenAIRealtimeConfig.objects.filter(
        model_name="gpt-4o-realtime-preview"
    ).update(model_name="gpt-realtime-1.5")

def backwards(apps, schema_editor):
    OpenAIRealtimeConfig = apps.get_model("tables", "OpenAIRealtimeConfig")
    OpenAIRealtimeConfig.objects.filter(
        model_name="gpt-realtime-1.5"
    ).update(model_name="gpt-4o-realtime-preview")

class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0176_alter_openairealtimeconfig_model_name"),
    ]
    operations = [
        migrations.RunPython(forwards, backwards),
    ]
