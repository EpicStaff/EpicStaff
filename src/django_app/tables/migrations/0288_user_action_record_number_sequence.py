from django.db import migrations


class Migration(migrations.Migration):
    """Create the deployment-wide sequence `user_audit.recorder` numbers user-action records from.

    `user_audit` owns no models and is not a Django app, so the sequence lives here, next to
    the audit filter presets. It backs no column: records are stored in the auditor.
    """

    dependencies = [
        ("tables", "0287_audit_filter_preset_domain"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE SEQUENCE user_action_record_number_seq;",
            reverse_sql="DROP SEQUENCE user_action_record_number_seq;",
        ),
    ]
