from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0149_classificationconditiongroup_field_expressions"),
    ]

    operations = [
        migrations.AddField(
            model_name="classificationconditiongroup",
            name="field_manipulations",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
