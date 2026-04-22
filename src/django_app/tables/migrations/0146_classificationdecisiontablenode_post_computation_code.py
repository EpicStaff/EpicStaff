from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0145_classification_decision_table_node"),
    ]

    operations = [
        migrations.AddField(
            model_name="classificationdecisiontablenode",
            name="post_computation_code",
            field=models.TextField(blank=True, default=None, null=True),
        ),
    ]
