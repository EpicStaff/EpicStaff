import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0171_merge_20260420_1647"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="classificationdecisiontablenode",
            name="pre_computation_code",
        ),
        migrations.RemoveField(
            model_name="classificationdecisiontablenode",
            name="post_computation_code",
        ),
        migrations.RemoveField(
            model_name="classificationdecisiontablenode",
            name="route_variable_name",
        ),
        migrations.RemoveField(
            model_name="classificationdecisiontablenode",
            name="expression_errors_as_false",
        ),
        migrations.AddField(
            model_name="classificationdecisiontablenode",
            name="pre_python_code",
            field=models.ForeignKey(
                default=None,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="cdt_pre_nodes",
                to="tables.pythoncode",
            ),
        ),
        migrations.AddField(
            model_name="classificationdecisiontablenode",
            name="post_python_code",
            field=models.ForeignKey(
                default=None,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="cdt_post_nodes",
                to="tables.pythoncode",
            ),
        ),
    ]
