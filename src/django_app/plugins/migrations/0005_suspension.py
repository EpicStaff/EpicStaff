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
        migrations.AddIndex(
            model_name='pluginownedresource',
            index=models.Index(condition=models.Q(('grant__isnull', True)), fields=['org'], name='plugins_owned_orphan_by_org'),
        ),
    ]
