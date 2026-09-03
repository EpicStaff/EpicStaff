# Hand-written migration — Migration C, part 3 of 3.
# Makes trigger fields non-null, removes old FKs from WebhookTrigger,
# and replaces the unique_together constraint with the new (path, provider_type) pair.
# Depends on 0186 which already deleted any orphaned config rows (trigger_id IS NULL),
# so the non-null enforcement here is safe.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0186_delete_orphan_webhook_configs"),
    ]

    operations = [
        # 1. Make NgrokWebhookConfig.trigger non-null
        migrations.AlterField(
            model_name="ngrokwebhookconfig",
            name="trigger",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="ngrok",
                to="tables.webhooktrigger",
            ),
        ),
        # 2. Make LocalhostWebhookConfig.trigger non-null
        migrations.AlterField(
            model_name="localhostwebhookconfig",
            name="trigger",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="localhost",
                to="tables.webhooktrigger",
            ),
        ),
        # 3. Clear old unique_together before removing the referenced fields
        migrations.AlterUniqueTogether(
            name="webhooktrigger",
            unique_together=set(),
        ),
        # 4. Remove ngrok_webhook_config FK from WebhookTrigger
        migrations.RemoveField(
            model_name="webhooktrigger",
            name="ngrok_webhook_config",
        ),
        # 5. Remove localhost_webhook_config FK from WebhookTrigger
        migrations.RemoveField(
            model_name="webhooktrigger",
            name="localhost_webhook_config",
        ),
    ]
