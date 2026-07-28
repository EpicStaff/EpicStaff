from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0148_classificationdecisiontablenode_output_variable_paths"),
    ]

    operations = [
        migrations.AddField(
            model_name="classificationconditiongroup",
            name="field_expressions",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
