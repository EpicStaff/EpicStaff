from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0153_migrate_note_nodes_from_metadata"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='crewnode',
            name='unique_graph_node_name_for_crew_node',
        ),
        migrations.RemoveConstraint(
            model_name='pythonnode',
            name='unique_graph_node_name_for_python_node',
        ),
        migrations.RemoveConstraint(
            model_name='fileextractornode',
            name='unique_graph_node_name_for_file_extractor_node',
        ),
        migrations.RemoveConstraint(
            model_name='audiotranscriptionnode',
            name='unique_graph_node_name_for_audio_transcriotion_node',
        ),
        migrations.RemoveConstraint(
            model_name='llmnode',
            name='unique_graph_node_name_for_llm_node',
        ),
        migrations.RemoveConstraint(
            model_name='subgraphnode',
            name='unique_graph_node_name_for_subgraph_node',
        ),
        migrations.RemoveConstraint(
            model_name='decisiontablenode',
            name='unique_graph_node_name_for_decision_table_node',
        ),
        migrations.RemoveConstraint(
            model_name='webhooktriggernode',
            name='unique_graph_node_name_for_webhook_nodes',
        ),
        migrations.RemoveConstraint(
            model_name='telegramtriggernode',
            name='unique_graph_node_name_for_telegram_trigger_nodes',
        )
    ]
