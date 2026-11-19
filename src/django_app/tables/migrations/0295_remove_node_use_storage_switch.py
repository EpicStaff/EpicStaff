from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tables', '0294_untick_grants_of_nodes_without_storage'),
    ]

    operations = [
        migrations.RemoveField(model_name='pythonnode', name='use_storage'),
        migrations.RemoveField(model_name='webhooktriggernode', name='use_storage'),
        migrations.RemoveField(
            model_name='classificationdecisiontablenode', name='pre_use_storage'
        ),
        migrations.RemoveField(
            model_name='classificationdecisiontablenode', name='post_use_storage'
        ),
    ]
