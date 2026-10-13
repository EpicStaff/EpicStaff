import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

ORG_SCOPED_TABLES = ("agents_agentdefinition", "agents_surface")


def _org_foreign_key():
    return models.ForeignKey(
        null=True,
        on_delete=django.db.models.deletion.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
        to="rbac.organization",
    )


def _created_by_foreign_key():
    return models.ForeignKey(
        blank=True,
        null=True,
        on_delete=django.db.models.deletion.SET_NULL,
        related_name="+",
        to=settings.AUTH_USER_MODEL,
    )


def _keep_org_not_null(table):
    return migrations.RunSQL(
        sql=f"ALTER TABLE {table} ALTER COLUMN org_id SET NOT NULL;",
        reverse_sql=f"ALTER TABLE {table} ALTER COLUMN org_id DROP NOT NULL;",
    )


class Migration(migrations.Migration):
    """Move AgentDefinition and Surface onto OrgScopedModel.

    `organization` is renamed to `org`, so existing rows keep their organization.
    The model state takes OrgScopedModel's nullable `org`; the DB keeps org_id NOT NULL.
    """

    dependencies = [
        ("agents", "0009_alter_agentdefinition_organization_and_more"),
        ("rbac", "0003_key_value_tables_resource_type"),
        ("tables", "0256_node_created_by"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="agentdefinition",
            name="unique_agent_definition_name_per_organization",
        ),
        migrations.RemoveConstraint(
            model_name="surface",
            name="uniq_surface_org_name",
        ),
        migrations.RenameField(
            model_name="agentdefinition",
            old_name="organization",
            new_name="org",
        ),
        migrations.RenameField(
            model_name="surface",
            old_name="organization",
            new_name="org",
        ),
        migrations.AlterField(
            model_name="agentdefinition",
            name="org",
            field=_org_foreign_key(),
        ),
        migrations.AlterField(
            model_name="surface",
            name="org",
            field=_org_foreign_key(),
        ),
        *[_keep_org_not_null(table) for table in ORG_SCOPED_TABLES],
        migrations.AddField(
            model_name="agentdefinition",
            name="created_by",
            field=_created_by_foreign_key(),
        ),
        migrations.AddField(
            model_name="surface",
            name="created_by",
            field=_created_by_foreign_key(),
        ),
        migrations.AddIndex(
            model_name="agentdefinition",
            index=models.Index(fields=["org"], name="agents_agen_org_id_4b1f04_idx"),
        ),
        migrations.AddIndex(
            model_name="surface",
            index=models.Index(fields=["org"], name="agents_surf_org_id_94a309_idx"),
        ),
        migrations.AddConstraint(
            model_name="agentdefinition",
            constraint=models.UniqueConstraint(
                fields=("org", "name"),
                name="unique_agent_definition_name_per_organization",
            ),
        ),
        migrations.AddConstraint(
            model_name="surface",
            constraint=models.UniqueConstraint(
                fields=("org", "name"),
                name="uniq_surface_org_name",
            ),
        ),
    ]
