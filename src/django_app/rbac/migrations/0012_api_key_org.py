"""Bind every USER API key to one organization.

Existing USER keys have no organization and there is no safe way to pick one for them
(an owner can belong to several), so they are deleted; their owners create new keys.
Sessions started with a deleted key keep their user and email; only
`SessionPrincipal.api_key` becomes NULL (its `on_delete=SET_NULL`). The SYSTEM key is kept.
Irreversible by design: deleted keys cannot be restored.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def delete_user_api_keys(apps, schema_editor):
    ApiKey = apps.get_model("rbac", "ApiKey")
    ApiKey.objects.filter(key_type="user").delete()
    # The delete queues deferred FK checks (SessionPrincipal.api_key); Postgres refuses the
    # AddConstraint ALTER TABLE below while they are pending, so run them now.
    schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")


class Migration(migrations.Migration):

    dependencies = [
        ("rbac", "0011_merge_retention_and_resource_types"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="apikey",
            name="api_key_type_invariants",
        ),
        migrations.AddField(
            model_name="apikey",
            name="org",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="api_keys",
                to="rbac.organization",
            ),
        ),
        migrations.RunPython(delete_user_api_keys, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="apikey",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("created_by__isnull", False),
                        ("key_type", "user"),
                        ("org__isnull", False),
                    ),
                    models.Q(
                        ("created_by__isnull", True),
                        ("expires_at__isnull", True),
                        ("key_type", "system"),
                        ("org__isnull", True),
                    ),
                    _connector="OR",
                ),
                name="api_key_type_invariants",
            ),
        ),
    ]
