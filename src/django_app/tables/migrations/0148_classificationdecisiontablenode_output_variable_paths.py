from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0147_classificationdecisiontablenode_input_maps"),
    ]

    operations = [
        migrations.AddField(
            model_name="classificationdecisiontablenode",
            name="pre_output_variable_path",
            field=models.CharField(blank=True, default=None, max_length=512, null=True),
        ),
        migrations.AddField(
            model_name="classificationdecisiontablenode",
            name="post_output_variable_path",
            field=models.CharField(blank=True, default=None, max_length=512, null=True),
        ),
    ]
