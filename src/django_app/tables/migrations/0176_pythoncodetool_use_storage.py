from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0175_merge_20260504_1000"),
    ]

    operations = [
        migrations.AddField(
            model_name="pythoncodetool",
            name="use_storage",
            field=models.BooleanField(default=False),
        ),
    ]
