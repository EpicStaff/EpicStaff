import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plugins', '0004_service_accounts_hooks_ownership_activity'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pluginactivityevent',
            name='action',
            field=models.CharField(choices=[('api_request', 'Api Request'), ('package_approved', 'Package Approved'), ('grant_created', 'Grant Created'), ('install_hook_succeeded', 'Install Hook Succeeded'), ('install_hook_failed', 'Install Hook Failed'), ('install_hook_retried', 'Install Hook Retried'), ('grant_suspended', 'Grant Suspended'), ('grant_resumed', 'Grant Resumed'), ('settings_changed', 'Settings Changed'), ('limits_changed', 'Limits Changed'), ('restarted', 'Restarted')], max_length=32),
        ),
        migrations.RemoveIndex(
            model_name='pluginactivityevent',
            name='plugins_activity_by_org',
        ),
        migrations.RemoveIndex(
            model_name='pluginactivityevent',
            name='plugins_activity_by_plugin',
        ),
        migrations.AddIndex(
            model_name='pluginactivityevent',
            index=models.Index(fields=['organization_id', '-created_at', '-id'], name='plugins_activity_by_org'),
        ),
        migrations.AddIndex(
            model_name='pluginactivityevent',
            index=models.Index(fields=['plugin_identifier', '-created_at', '-id'], name='plugins_activity_by_plugin'),
        ),
        migrations.AddIndex(
            model_name='pluginactivityevent',
            index=models.Index(fields=['organization_id', 'plugin_identifier', '-created_at', '-id'], name='plugins_activity_by_org_plugin'),
        ),
        migrations.AlterField(
            model_name='pluginownedresource',
            name='org',
            field=models.ForeignKey(db_index=False, on_delete=django.db.models.deletion.CASCADE, related_name='plugin_owned_resources', to='rbac.organization'),
        ),
        migrations.AlterField(
            model_name='pluginownedresource',
            name='content_type',
            field=models.ForeignKey(db_index=False, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='contenttypes.contenttype'),
        ),
        migrations.AddIndex(
            model_name='pluginownedresource',
            index=models.Index(condition=models.Q(('grant__isnull', True)), fields=['org'], name='plugins_owned_orphan_by_org'),
        ),
    ]
