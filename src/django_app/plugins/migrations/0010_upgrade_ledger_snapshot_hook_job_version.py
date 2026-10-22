from django.db import migrations, models
from django.db.models import OuterRef, Subquery


def copy_claimed_package_versions(apps, schema_editor):
    """A job claimed before this migration gets its package's version, while the package is there."""
    PluginHookJob = apps.get_model("plugins", "PluginHookJob")
    PluginPackage = apps.get_model("plugins", "PluginPackage")
    PluginHookJob.objects.filter(claimed_at__isnull=False, package__isnull=False).update(
        package_version=Subquery(
            PluginPackage.objects.filter(pk=OuterRef("package_id")).values("version")[:1]
        )
    )


class Migration(migrations.Migration):
    """The upgrade's ledger snapshot, the hook job's version as text, the version a backup was
    taken for, the restore's pre-restore file name, and a narrower backup retention index. Upgrades opened before this migration keep a null snapshot, and
    `database_changed` falls back to comparing with the version they upgrade from."""

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
        migrations.RunPython(copy_claimed_package_versions, migrations.RunPython.noop),
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
