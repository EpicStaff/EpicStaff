from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0146_classificationdecisiontablenode_post_computation_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="classificationdecisiontablenode",
            name="pre_input_map",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="classificationdecisiontablenode",
            name="post_input_map",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
