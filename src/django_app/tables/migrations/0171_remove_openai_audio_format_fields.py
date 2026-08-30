from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0170_merge_20260416_1456"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="openairealtimeconfig",
            name="input_audio_format",
        ),
        migrations.RemoveField(
            model_name="openairealtimeconfig",
            name="output_audio_format",
        ),
    ]
