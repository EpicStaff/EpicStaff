import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Destructive migration: wipes all FlowAssistantConversation rows, then
    replaces the `user` FK with `organization_user`, adds `title`, and `deleted_at`."""

    dependencies = [
        ("tables", "0181_flow_assistant"),
    ]

    operations = [
        # Wipe any pre-existing dev rows. The plan explicitly designates this
        # migration as destructive on the demo/feature/mod-v2-flow-assistant
        # branch — the table contains only test data and the new column set
        # (organization_user, title, deleted_at) cannot be populated retroactively
        # from the dropped `user` column.
        migrations.RunSQL(
            sql="DELETE FROM tables_flowassistantconversation;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Drop the old user FK column
        migrations.RemoveField(
            model_name="flowassistantconversation",
            name="user",
        ),
        # Add organization_user FK
        migrations.AddField(
            model_name="flowassistantconversation",
            name="organization_user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="flow_assistant_conversations",
                to="tables.organizationuser",
                # Temporary default is required by Django for non-nullable field on existing table.
                # The table is empty on all branch envs (destructive is acceptable per spec).
                default=None,
                null=True,
            ),
            preserve_default=False,
        ),
        # Make the field non-nullable now that every row has been set
        migrations.AlterField(
            model_name="flowassistantconversation",
            name="organization_user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="flow_assistant_conversations",
                to="tables.organizationuser",
                null=False,
            ),
        ),
        # Add title
        migrations.AddField(
            model_name="flowassistantconversation",
            name="title",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        # Add deleted_at with db_index
        migrations.AddField(
            model_name="flowassistantconversation",
            name="deleted_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
