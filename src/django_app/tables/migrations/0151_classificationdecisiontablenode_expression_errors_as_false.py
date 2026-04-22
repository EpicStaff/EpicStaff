from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0150_classificationconditiongroup_field_manipulations"),
    ]

    operations = [
        migrations.AddField(
            model_name="classificationdecisiontablenode",
            name="expression_errors_as_false",
            field=models.BooleanField(default=False),
        ),
    ]
