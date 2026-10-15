"""Recycle bin soft delete: drops `is_soft_deleted` for `active`, adds soft delete to the
models that lacked it, the `soft_delete_batch` column, the soft-delete managers, the
consistency checks and the unique constraints that only count live rows.
"""

import django.core.validators
import django.db.models.functions.text
import django.db.models.manager
from django.db import migrations, models


APP_LABEL = "tables"


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


def align_section_soft_delete_columns(apps, schema_editor):
    # ClassificationConditionGroupSection had no consistency check before this
    # migration, so its flag and timestamp may disagree. The flag wins: it is what
    # every query reads. A binned row without a timestamp gets "now", which starts
    # its recycle-bin retention from this migration.
    table = schema_editor.quote_name(
        apps.get_model("tables", "ClassificationConditionGroupSection")._meta.db_table
    )
    schema_editor.execute(f"UPDATE {table} SET soft_deleted_at = NULL WHERE active AND soft_deleted_at IS NOT NULL")
    schema_editor.execute(f"UPDATE {table} SET soft_deleted_at = now() WHERE NOT active AND soft_deleted_at IS NULL")


class Migration(migrations.Migration):

    replaces = [
        ('tables', '0259_drop_is_soft_deleted'),
        ('tables', '0260_alter_agentgraphrag_options_and_more'),
        ('tables', '0261_soft_delete_batch'),
        ('tables', '0262_merge_20261005_1124'),
        ('tables', '0263_soft_delete_owned_children'),
        ('tables', '0264_soft_delete_mcp_tool'),
        ('tables', '0265_storage_file_soft_delete'),
        ('tables', '0266_key_value_table_soft_delete'),
        ('tables', '0267_settings_resources_soft_delete'),
        ('tables', '0268_merge_20261009_1151'),
        ('tables', '0269_merge_20261012_1214'),
        ('tables', '0270_merge_20261013_1321'),
        ('tables', '0271_secret_live_user_names_unique'),
        ('tables', '0272_merge_20261014_1022'),
    ]

    dependencies = [
        ('tables', '0269_soft_delete_active_flag'),
        ('agents', '0016_recycle_bin_soft_delete'),
        ('rbac', '0006_merge_20261009_0941'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='classificationconditiongroupsection',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='keyvaluetable',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='keyvaluetableentry',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='knowledgenodegraphragbasicsearchconfig',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='knowledgenodegraphragdriftsearchconfig',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='knowledgenodegraphragglobalsearchconfig',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='knowledgenodegraphraglocalsearchconfig',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='knowledgenodenaiveragsearchconfig',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='localhostwebhookconfig',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='mcptool',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects', 'verbose_name': 'MCP Tool Data', 'verbose_name_plural': 'MCP Tool Data'},
        ),
        migrations.AlterModelOptions(
            name='mcptoolfavorite',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='ngrokwebhookconfig',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='pythoncodetoolfavorite',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='realtimeagentdefinition',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='realtimechannel',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='secret',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='storagefile',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='twiliochannel',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='webhooktrigger',
            options={'base_manager_name': 'all_objects', 'default_manager_name': 'objects'},
        ),
        migrations.AlterModelManagers(
            name='classificationconditiongroupsection',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='keyvaluetable',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='keyvaluetableentry',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='knowledgenodegraphragbasicsearchconfig',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='knowledgenodegraphragdriftsearchconfig',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='knowledgenodegraphragglobalsearchconfig',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='knowledgenodegraphraglocalsearchconfig',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='knowledgenodenaiveragsearchconfig',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='localhostwebhookconfig',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='mcptool',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='mcptoolfavorite',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='ngrokwebhookconfig',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='pythoncodetoolfavorite',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='realtimeagentdefinition',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='realtimechannel',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='secret',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='storagefile',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='twiliochannel',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='webhooktrigger',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.RemoveConstraint(
            model_name='agentgraphrag',
            name='tables_agentgraphrag_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='agentnaiverag',
            name='tables_agentnaiverag_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='agentnode',
            name='tables_agentnode_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='agentnodetask',
            name='tables_agentnodetask_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='agentpythoncodetoolconfigs',
            name='tables_agentpythoncodetoolconfigs_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='agentpythoncodetools',
            name='tables_agentpythoncodetools_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='audiotranscriptionnode',
            name='tables_audiotranscriptionnode_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='baseragtype',
            name='tables_baseragtype_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='classificationconditiongroup',
            name='tables_classificationconditiongroup_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='classificationdecisiontablenode',
            name='tables_classificationdecisiontablenode_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='classificationdecisiontableprompt',
            name='tables_classificationdecisiontableprompt_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='condition',
            name='tables_condition_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='conditiongroup',
            name='tables_conditiongroup_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='crewnode',
            name='tables_crewnode_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='decisiontablenode',
            name='tables_decisiontablenode_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='documentmetadata',
            name='tables_documentmetadata_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='edge',
            name='tables_edge_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='endnode',
            name='tables_endnode_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='fileextractornode',
            name='tables_fileextractornode_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='flowassistant',
            name='tables_flowassistant_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='flowassistantconversation',
            name='tables_flowassistantconversation_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='flowassistantmessage',
            name='tables_flowassistantmessage_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='graph',
            name='tables_graph_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='graph',
            name='unique_graph_name_per_org',
        ),
        migrations.RemoveConstraint(
            model_name='graphnote',
            name='tables_graphnote_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='graphorganization',
            name='tables_graphorganization_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='graphorganizationuser',
            name='tables_graphorganizationuser_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='graphrag',
            name='tables_graphrag_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='graphragdocument',
            name='tables_graphragdocument_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='graphstoragefile',
            name='tables_graphstoragefile_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='graphversion',
            name='tables_graphversion_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='keyvaluenode',
            name='tables_keyvaluenode_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='keyvaluetable',
            name='unique_key_value_table_name_per_org_ci',
        ),
        migrations.RemoveConstraint(
            model_name='knowledgenode',
            name='tables_knowledgenode_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='mcptool',
            name='unique_mcptool_name_per_org',
        ),
        migrations.RemoveConstraint(
            model_name='naiverag',
            name='tables_naiverag_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='naiveragchunk',
            name='tables_naiveragchunk_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='naiveragdocumentconfig',
            name='tables_naiveragdocumentconfig_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='naiveragembedding',
            name='tables_naiveragembedding_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='naiveragpreviewchunk',
            name='tables_naiveragpreviewchunk_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='pythoncodetool',
            name='tables_pythoncodetool_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='pythoncodetool',
            name='unique_pythoncodetool_name_per_org',
        ),
        migrations.RemoveConstraint(
            model_name='pythoncodetoolconfig',
            name='tables_pythoncodetoolconfig_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='pythonnode',
            name='tables_pythonnode_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='scheduletriggernode',
            name='tables_scheduletriggernode_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='secret',
            name='unique_secret_name_per_org',
        ),
        migrations.RemoveConstraint(
            model_name='sourcecollection',
            name='tables_sourcecollection_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='sourcecollection',
            name='unique_collection_name_per_org',
        ),
        migrations.RemoveConstraint(
            model_name='startnode',
            name='tables_startnode_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='storagefile',
            name='unique_storage_file_per_org',
        ),
        migrations.RemoveConstraint(
            model_name='subgraphnode',
            name='tables_subgraphnode_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='tasknode',
            name='tables_tasknode_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='taskpythoncodetoolconfigs',
            name='tables_taskpythoncodetoolconfigs_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='taskpythoncodetools',
            name='tables_taskpythoncodetools_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='telegramtriggernode',
            name='tables_telegramtriggernode_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='telegramtriggernodefield',
            name='tables_telegramtriggernodefield_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='webhooktriggerauth',
            name='tables_webhooktriggerauth_soft_delete_consistency',
        ),
        migrations.RemoveConstraint(
            model_name='webhooktriggernode',
            name='tables_webhooktriggernode_soft_delete_consistency',
        ),
        migrations.RunPython(migrations.RunPython.noop, copy_active_to_is_soft_deleted),
        migrations.RemoveField(
            model_name='agentgraphrag',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='agentnaiverag',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='agentnode',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='agentnodetask',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='agentpythoncodetoolconfigs',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='agentpythoncodetools',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='audiotranscriptionnode',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='baseragtype',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='classificationconditiongroup',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='classificationconditiongroupsection',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='classificationdecisiontablenode',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='classificationdecisiontableprompt',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='condition',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='conditiongroup',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='crewnode',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='decisiontablenode',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='documentmetadata',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='edge',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='endnode',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='fileextractornode',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='flowassistant',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='flowassistantconversation',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='flowassistantmessage',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='graph',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='graphnote',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='graphorganization',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='graphorganizationuser',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='graphrag',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='graphragdocument',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='graphstoragefile',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='graphversion',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='keyvaluenode',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='knowledgenode',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='naiverag',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='naiveragchunk',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='naiveragdocumentconfig',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='naiveragembedding',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='naiveragpreviewchunk',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='pythoncodetool',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='pythoncodetoolconfig',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='pythonnode',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='scheduletriggernode',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='sourcecollection',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='startnode',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='subgraphnode',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='tasknode',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='taskpythoncodetoolconfigs',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='taskpythoncodetools',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='telegramtriggernode',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='telegramtriggernodefield',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='webhooktriggerauth',
            name='is_soft_deleted',
        ),
        migrations.RemoveField(
            model_name='webhooktriggernode',
            name='is_soft_deleted',
        ),
        migrations.AddField(
            model_name='agentgraphrag',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='agentnaiverag',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='agentnode',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='agentnodetask',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='agentpythoncodetoolconfigs',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='agentpythoncodetools',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='audiotranscriptionnode',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='baseragtype',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='classificationconditiongroup',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='classificationconditiongroupsection',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='classificationdecisiontablenode',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='classificationdecisiontableprompt',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='condition',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='conditiongroup',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='crewnode',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='decisiontablenode',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='documentmetadata',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='edge',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='endnode',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='fileextractornode',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='flowassistant',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='flowassistantconversation',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='flowassistantmessage',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='graph',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='graphnote',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='graphorganization',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='graphorganizationuser',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='graphrag',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='graphragdocument',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='graphstoragefile',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='graphversion',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='keyvaluenode',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='keyvaluetable',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='keyvaluetable',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='keyvaluetable',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='keyvaluetableentry',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='keyvaluetableentry',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='keyvaluetableentry',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='knowledgenode',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='knowledgenodegraphragbasicsearchconfig',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='knowledgenodegraphragbasicsearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='knowledgenodegraphragbasicsearchconfig',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='knowledgenodegraphragdriftsearchconfig',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='knowledgenodegraphragdriftsearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='knowledgenodegraphragdriftsearchconfig',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='knowledgenodegraphragglobalsearchconfig',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='knowledgenodegraphragglobalsearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='knowledgenodegraphragglobalsearchconfig',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='knowledgenodegraphraglocalsearchconfig',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='knowledgenodegraphraglocalsearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='knowledgenodegraphraglocalsearchconfig',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='knowledgenodenaiveragsearchconfig',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='knowledgenodenaiveragsearchconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='knowledgenodenaiveragsearchconfig',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='localhostwebhookconfig',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='localhostwebhookconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='localhostwebhookconfig',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='mcptool',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='mcptool',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='mcptool',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='mcptoolfavorite',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='mcptoolfavorite',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='mcptoolfavorite',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='naiverag',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='naiveragchunk',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='naiveragdocumentconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='naiveragembedding',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='naiveragpreviewchunk',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='ngrokwebhookconfig',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='ngrokwebhookconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='ngrokwebhookconfig',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='pythoncodetool',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='pythoncodetoolconfig',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='pythoncodetoolfavorite',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='pythoncodetoolfavorite',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='pythoncodetoolfavorite',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='pythonnode',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='realtimeagentdefinition',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='realtimeagentdefinition',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='realtimeagentdefinition',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='realtimechannel',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='realtimechannel',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='realtimechannel',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='scheduletriggernode',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='secret',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='secret',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='secret',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='sourcecollection',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='startnode',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='storagefile',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='storagefile',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='storagefile',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='subgraphnode',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='tasknode',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='taskpythoncodetoolconfigs',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='taskpythoncodetools',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='telegramtriggernode',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='telegramtriggernodefield',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='twiliochannel',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='twiliochannel',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='twiliochannel',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='webhooktrigger',
            name='active',
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name='webhooktrigger',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='webhooktrigger',
            name='soft_deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='webhooktriggerauth',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='webhooktriggernode',
            name='soft_delete_batch',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AlterField(
            model_name='twiliochannel',
            name='phone_number',
            field=models.CharField(blank=True, help_text='E.164 format, e.g. +15551234567', max_length=50, null=True),
        ),
        migrations.AlterField(
            model_name='webhooktrigger',
            name='path',
            field=models.CharField(max_length=255, validators=[django.core.validators.RegexValidator(message='Path may only contain letters, numbers, hyphens, and underscores, and must start with a letter or number.', regex='^[a-zA-Z0-9]{1}[a-zA-Z0-9-_]*$')]),
        ),
        migrations.AddConstraint(
            model_name='agentgraphrag',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_agentgraphrag_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='agentnaiverag',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_agentnaiverag_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='agentnode',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_agentnode_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='agentnodetask',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_agentnodetask_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='agentpythoncodetoolconfigs',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_agentpythoncodetoolconfigs_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='agentpythoncodetools',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_agentpythoncodetools_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='audiotranscriptionnode',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_audiotranscriptionnode_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='baseragtype',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_baseragtype_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='classificationconditiongroup',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_classificationconditiongroup_soft_delete_consistency'),
        ),
        migrations.RunPython(align_section_soft_delete_columns, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='classificationconditiongroupsection',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_classificationconditiongroupsection_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='classificationdecisiontablenode',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_classificationdecisiontablenode_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='classificationdecisiontableprompt',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_classificationdecisiontableprompt_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='condition',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_condition_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='conditiongroup',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_conditiongroup_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='crewnode',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_crewnode_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='decisiontablenode',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_decisiontablenode_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='documentmetadata',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_documentmetadata_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='edge',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_edge_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='endnode',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_endnode_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='fileextractornode',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_fileextractornode_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='flowassistant',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_flowassistant_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='flowassistantconversation',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_flowassistantconversation_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='flowassistantmessage',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_flowassistantmessage_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='graph',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_graph_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='graph',
            constraint=models.UniqueConstraint(condition=models.Q(('active', True)), fields=('org', 'name'), name='unique_graph_name_per_org'),
        ),
        migrations.AddConstraint(
            model_name='graphnote',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_graphnote_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='graphorganization',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_graphorganization_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='graphorganizationuser',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_graphorganizationuser_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='graphrag',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_graphrag_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='graphragdocument',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_graphragdocument_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='graphstoragefile',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_graphstoragefile_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='graphversion',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_graphversion_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='keyvaluenode',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_keyvaluenode_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='keyvaluetable',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_keyvaluetable_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='keyvaluetable',
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower('name'), models.F('org'), condition=models.Q(('active', True)), name='unique_key_value_table_name_per_org_ci'),
        ),
        migrations.AddConstraint(
            model_name='keyvaluetableentry',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_keyvaluetableentry_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='knowledgenode',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_knowledgenode_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='knowledgenodegraphragbasicsearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_knowledgenodegraphragbasicsearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='knowledgenodegraphragdriftsearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_knowledgenodegraphragdriftsearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='knowledgenodegraphragglobalsearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_knowledgenodegraphragglobalsearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='knowledgenodegraphraglocalsearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_knowledgenodegraphraglocalsearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='knowledgenodenaiveragsearchconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_knowledgenodenaiveragsearchconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='localhostwebhookconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_localhostwebhookconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='mcptool',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_mcptool_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='mcptool',
            constraint=models.UniqueConstraint(condition=models.Q(('active', True)), fields=('org', 'name'), name='unique_mcptool_name_per_org'),
        ),
        migrations.AddConstraint(
            model_name='mcptoolfavorite',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_mcptoolfavorite_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='naiverag',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_naiverag_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='naiveragchunk',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_naiveragchunk_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='naiveragdocumentconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_naiveragdocumentconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='naiveragembedding',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_naiveragembedding_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='naiveragpreviewchunk',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_naiveragpreviewchunk_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='ngrokwebhookconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_ngrokwebhookconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='pythoncodetool',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_pythoncodetool_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='pythoncodetool',
            constraint=models.UniqueConstraint(condition=models.Q(('active', True)), fields=('org', 'name'), name='unique_pythoncodetool_name_per_org'),
        ),
        migrations.AddConstraint(
            model_name='pythoncodetoolconfig',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_pythoncodetoolconfig_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='pythoncodetoolfavorite',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_pythoncodetoolfavorite_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='pythonnode',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_pythonnode_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='realtimeagentdefinition',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_realtimeagentdefinition_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='realtimechannel',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_realtimechannel_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='scheduletriggernode',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_scheduletriggernode_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='secret',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_secret_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='secret',
            constraint=models.UniqueConstraint(condition=models.Q(('active', True), ('system', False)), fields=('org', 'name'), name='unique_secret_name_per_org'),
        ),
        migrations.AddConstraint(
            model_name='sourcecollection',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_sourcecollection_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='sourcecollection',
            constraint=models.UniqueConstraint(condition=models.Q(('active', True)), fields=('org', 'collection_name'), name='unique_collection_name_per_org'),
        ),
        migrations.AddConstraint(
            model_name='startnode',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_startnode_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='storagefile',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_storagefile_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='storagefile',
            constraint=models.UniqueConstraint(condition=models.Q(('active', True)), fields=('org', 'path'), name='unique_active_storage_file_per_org'),
        ),
        migrations.AddConstraint(
            model_name='subgraphnode',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_subgraphnode_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='tasknode',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_tasknode_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='taskpythoncodetoolconfigs',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_taskpythoncodetoolconfigs_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='taskpythoncodetools',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_taskpythoncodetools_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='telegramtriggernode',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_telegramtriggernode_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='telegramtriggernodefield',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_telegramtriggernodefield_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='twiliochannel',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_twiliochannel_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='twiliochannel',
            constraint=models.UniqueConstraint(condition=models.Q(('active', True)), fields=('phone_number',), name='unique_live_twilio_phone_number'),
        ),
        migrations.AddConstraint(
            model_name='webhooktrigger',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_webhooktrigger_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='webhooktrigger',
            constraint=models.UniqueConstraint(condition=models.Q(('active', True)), fields=('path',), name='unique_live_webhook_path'),
        ),
        migrations.AddConstraint(
            model_name='webhooktriggerauth',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_webhooktriggerauth_soft_delete_consistency'),
        ),
        migrations.AddConstraint(
            model_name='webhooktriggernode',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('active', True), ('soft_deleted_at__isnull', True)), models.Q(('active', False), ('soft_deleted_at__isnull', False)), _connector='OR'), name='tables_webhooktriggernode_soft_delete_consistency'),
        ),
    ]
