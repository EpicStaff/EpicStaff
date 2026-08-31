from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0177_update_existing_openai_model_name"),
    ]

    operations = [
        migrations.CreateModel(
            name="LocalhostWebhookConfig",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=50, unique=True)),
                ("domain", models.CharField(blank=True, help_text="Optional local domain or URL", max_length=255, null=True)),
            ],
        ),
        migrations.AddField(
            model_name="webhooktrigger",
            name="localhost_webhook_config",
            field=models.ForeignKey(
                default=None,
                null=True,
                on_delete=django.db.models.deletion.SET_DEFAULT,
                to="tables.localhostwebhookconfig",
            ),
        ),
    ]
