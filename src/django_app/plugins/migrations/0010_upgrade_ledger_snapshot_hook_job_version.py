from django.db import migrations, models


class Migration(migrations.Migration):
    """The upgrade's ledger snapshot, the hook job's version as text, the version a backup was
    taken for, the restore's pre-restore file name, and a narrower backup retention index."""

    dependencies = [
        ("plugins", "0009_development_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="pluginupgrade",
            name="ledger_at_migrations",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="pluginhookjob",
            name="package_version",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="plugindatabasebackup",
            name="taken_for_version",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="plugindatabaserestore",
            name="pre_restore_file_name",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.RemoveIndex(
            model_name="plugindatabasebackup",
            name="plugins_backup_retention",
        ),
        migrations.AddIndex(
            model_name="plugindatabasebackup",
            index=models.Index(
                fields=["plugin_database", "deleted_at", "created_at"],
                name="plugins_backup_retention",
            ),
        ),
    ]
