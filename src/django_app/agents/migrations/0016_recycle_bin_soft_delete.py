"""Recycle bin soft delete: drops `is_soft_deleted` for `active`, adds soft delete to the
models that lacked it, the `soft_delete_batch` column, the soft-delete managers, the
consistency checks and the unique constraints that only count live rows.
"""

import django.db.models.manager
from django.conf import settings
from django.db import migrations, models


APP_LABEL = "agents"


def _soft_delete_tables(apps):
    for model in apps.get_app_config(APP_LABEL).get_models():
        field_names = {field.name for field in model._meta.local_fields}
        if {"active", "is_soft_deleted"} <= field_names:
            yield model._meta.db_table


def copy_active_to_is_soft_deleted(apps, schema_editor):
    for table in _soft_delete_tables(apps):
        schema_editor.execute(
            f"UPDATE {schema_editor.quote_name(table)} SET is_soft_deleted = true WHERE NOT active"
        )


class Migration(migrations.Migration):

    replaces = [
        ('agents', '0011_drop_is_soft_deleted'),
        ('agents', '0012_alter_agentinlinesurface_options_and_more'),
        ('agents', '0013_soft_delete_batch'),
        ('agents', '0014_soft_delete_owned_children'),
        ('agents', '0015_soft_delete_surface'),
        ('agents', '0016_soft_delete_agent_definition'),
        ('agents', '0017_merge_20261009_1151'),
        ('agents', '0018_merge_20261012_1214'),
        ('agents', '0019_unique_names_on_org_live_only'),
    ]

    dependencies = [
        ('agents', '0015_soft_delete_active_flag'),
        ('rbac', '0006_merge_20261009_0941'),
        ('tables', '0268_merge_20261013_1631'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='agentdefaultsurface',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='agentdefinition',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='agentinlinesurfacegraphdriftsearchconfig',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='agentinlinesurfacegraphglobalsearchconfig',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='inlinesurfacegraphdriftsearchconfig',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='inlinesurfacegraphglobalsearchconfig',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='surface',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='surfacegraphdriftsearchconfig',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='surfacegraphglobalsearchconfig',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='surfacemcptool',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='surfacestorageitem',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelManagers(
            name='agentdefaultsurface',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='agentdefinition',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='agentinlinesurfacegraphdriftsearchconfig',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='agentinlinesurfacegraphglobalsearchconfig',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='inlinesurfacegraphdriftsearchconfig',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='inlinesurfacegraphglobalsearchconfig',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='surface',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='surfacegraphdriftsearchconfig',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='surfacegraphglobalsearchconfig',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='surfacemcptool',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='surfacestorageitem',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.RemoveConstraint(
            model_name='agentdefinition',
            name='unique_agent_definition_name_per_organization',
        ),
        migrations.RemoveConstraint(
            model_name='agentinlinesurface',
            name='agents_agentinlinesurface_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='agentinlinesurfacegraphbasicsearchconfig',
            name='agents_agentinlinesurfacegraphbasicsearchconfig_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='agentinlinesurfacegraphlocalsearchconfig',
            name='agents_agentinlinesurfacegraphlocalsearchconfig_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='agentinlinesurfacemcptool',
            name='agents_agentinlinesurfacemcptool_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='agentinlinesurfacenaivesearchconfig',
            name='agents_agentinlinesurfacenaivesearchconfig_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='agentinlinesurfacepythontool',
            name='agents_agentinlinesurfacepythontool_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='agentinlinesurfacestorageitem',
            name='agents_agentinlinesurfacestorageitem_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='inlinesurface',
            name='agents_inlinesurface_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='inlinesurfacegraphbasicsearchconfig',
            name='agents_inlinesurfacegraphbasicsearchconfig_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='inlinesurfacegraphlocalsearchconfig',
            name='agents_inlinesurfacegraphlocalsearchconfig_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='inlinesurfaceknowledge',
            name='agents_inlinesurfaceknowledge_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='inlinesurfacemcptool',
            name='agents_inlinesurfacemcptool_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='inlinesurfacenaivesearchconfig',
            name='agents_inlinesurfacenaivesearchconfig_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='inlinesurfacepythontool',
            name='agents_inlinesurfacepythontool_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='inlinesurfacestorageitem',
            name='agents_inlinesurfacestorageitem_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='surface',
            name='uniq_surface_org_name',
        ),
        migrations.RemoveConstraint(
            model_name='surfacegraphbasicsearchconfig',
            name='agents_surfacegraphbasicsearchconfig_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='surfacegraphlocalsearchconfig',
            name='agents_surfacegraphlocalsearchconfig_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='surfaceknowledge',
            name='agents_surfaceknowledge_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='surfacenaivesearchconfig',
            name='agents_surfacenaivesearchconfig_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='surfacepythontool',
            name='agents_surfacepythontool_soft_delete_consistency',
        ),
        migrations.RunPython(migrations.RunPython.noop, copy_active_to_is_soft_deleted),
        migrations.RemoveField(
            model_name='agentinlinesurface',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='agentinlinesurfacegraphbasicsearchconfig',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='agentinlinesurfacegraphlocalsearchconfig',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='agentinlinesurfaceknowledge',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='agentinlinesurfacemcptool',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='agentinlinesurfacenaivesearchconfig',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='agentinlinesurfacepythontool',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='agentinlinesurfacestorageitem',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='inlinesurface',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='inlinesurfacegraphbasicsearchconfig',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='inlinesurfacegraphlocalsearchconfig',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='inlinesurfaceknowledge',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='inlinesurfacemcptool',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='inlinesurfacenaivesearchconfig',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='inlinesurfacepythontool',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='inlinesurfacestorageitem',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='surfacegraphbasicsearchconfig',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='surfacegraphlocalsearchconfig',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='surfaceknowledge',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='surfacenaivesearchconfig',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='surfacepythontool',
            name='is_soft_deleted',
        ),
        migrations.AddField(
            model_name='agentdefaultsurface',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='agentdefaultsurface',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='agentdefaultsurface',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='agentdefinition',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='agentdefinition',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='agentdefinition',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='agentinlinesurface',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='agentinlinesurfacegraphbasicsearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='agentinlinesurfacegraphdriftsearchconfig',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='agentinlinesurfacegraphdriftsearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='agentinlinesurfacegraphdriftsearchconfig',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='agentinlinesurfacegraphglobalsearchconfig',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='agentinlinesurfacegraphglobalsearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='agentinlinesurfacegraphglobalsearchconfig',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='agentinlinesurfacegraphlocalsearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='agentinlinesurfaceknowledge',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='agentinlinesurfacemcptool',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='agentinlinesurfacenaivesearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='agentinlinesurfacepythontool',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='agentinlinesurfacestorageitem',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='inlinesurface',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='inlinesurfacegraphbasicsearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='inlinesurfacegraphdriftsearchconfig',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='inlinesurfacegraphdriftsearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='inlinesurfacegraphdriftsearchconfig',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='inlinesurfacegraphglobalsearchconfig',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='inlinesurfacegraphglobalsearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='inlinesurfacegraphglobalsearchconfig',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='inlinesurfacegraphlocalsearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='inlinesurfaceknowledge',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='inlinesurfacemcptool',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='inlinesurfacenaivesearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='inlinesurfacepythontool',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='inlinesurfacestorageitem',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='surface',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='surface',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='surface',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='surfacegraphbasicsearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='surfacegraphdriftsearchconfig',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='surfacegraphdriftsearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='surfacegraphdriftsearchconfig',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='surfacegraphglobalsearchconfig',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='surfacegraphglobalsearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='surfacegraphglobalsearchconfig',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='surfacegraphlocalsearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='surfaceknowledge',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='surfacemcptool',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='surfacemcptool',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='surfacemcptool',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='surfacenaivesearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='surfacepythontool',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='surfacestorageitem',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='surfacestorageitem',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='surfacestorageitem',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name='agentdefaultsurface',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_agentdefaultsurface_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='agentdefinition',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_agentdefinition_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='agentdefinition',
            constraint=models.UniqueConstraint(condition=models.Q(('active', True)), fields=('org', 'name'), name='unique_agent_definition_name_per_organization'),
        ),
        migrations.AddConstraint(
            model_name='agentinlinesurface',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_agentinlinesurface_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='agentinlinesurfacegraphbasicsearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_agentinlinesurfacegraphbasicsearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='agentinlinesurfacegraphdriftsearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_agentinlinesurfacegraphdriftsearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='agentinlinesurfacegraphglobalsearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_agentinlinesurfacegraphglobalsearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='agentinlinesurfacegraphlocalsearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_agentinlinesurfacegraphlocalsearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='agentinlinesurfacemcptool',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_agentinlinesurfacemcptool_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='agentinlinesurfacenaivesearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_agentinlinesurfacenaivesearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='agentinlinesurfacepythontool',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_agentinlinesurfacepythontool_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='agentinlinesurfacestorageitem',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_agentinlinesurfacestorageitem_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='inlinesurface',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_inlinesurface_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='inlinesurfacegraphbasicsearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_inlinesurfacegraphbasicsearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='inlinesurfacegraphdriftsearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_inlinesurfacegraphdriftsearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='inlinesurfacegraphglobalsearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_inlinesurfacegraphglobalsearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='inlinesurfacegraphlocalsearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_inlinesurfacegraphlocalsearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='inlinesurfaceknowledge',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_inlinesurfaceknowledge_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='inlinesurfacemcptool',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_inlinesurfacemcptool_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='inlinesurfacenaivesearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_inlinesurfacenaivesearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='inlinesurfacepythontool',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_inlinesurfacepythontool_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='inlinesurfacestorageitem',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_inlinesurfacestorageitem_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='surface',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_surface_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='surface',
            constraint=models.UniqueConstraint(condition=models.Q(('active', True)), fields=('org', 'name'), name='uniq_surface_org_name'),
        ),
        migrations.AddConstraint(
            model_name='surfacegraphbasicsearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_surfacegraphbasicsearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='surfacegraphdriftsearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_surfacegraphdriftsearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='surfacegraphglobalsearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_surfacegraphglobalsearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='surfacegraphlocalsearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_surfacegraphlocalsearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='surfaceknowledge',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_surfaceknowledge_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='surfacemcptool',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_surfacemcptool_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='surfacenaivesearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_surfacenaivesearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='surfacepythontool',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_surfacepythontool_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='surfacestorageitem',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='agents_surfacestorageitem_soft_delete_consistency'),
        ),
    ]
