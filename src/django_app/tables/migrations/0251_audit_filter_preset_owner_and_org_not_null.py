import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def delete_unreachable_presets(apps, schema_editor):
    # Presets are visible only to their owner inside their org, so a row
    # missing either can never be listed, read or deleted through the API -
    # there is nothing to backfill it from, and it would block NOT NULL.
    AuditFilterPreset = apps.get_model("tables", "AuditFilterPreset")
    AuditFilterPreset.objects.filter(
        models.Q(created_by__isnull=True) | models.Q(org__isnull=True)
    ).delete()


class Migration(migrations.Migration):
    """Make AuditFilterPreset's owner and org mandatory.

    `org` is enforced with plain RunSQL and no state operation, like the other
    OrgScopedModel tables (see 0209_realtime_channel_org_not_null): the mixin's
    field stays null=True in Django state. `created_by` is overridden on the
    model itself (CASCADE, non-null), so it gets a real AlterField.
    """

    dependencies = [
        ("tables", "0250_merge_audit_traile_migrations_5"),
    ]

    operations = [
        migrations.RunPython(delete_unreachable_presets, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="auditfilterpreset",
            name="created_by",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunSQL(
            sql="ALTER TABLE tables_auditfilterpreset ALTER COLUMN org_id SET NOT NULL;",
            reverse_sql="ALTER TABLE tables_auditfilterpreset ALTER COLUMN org_id DROP NOT NULL;",
        ),
    ]
