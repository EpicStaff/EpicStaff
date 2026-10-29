from django.db import migrations, models


class Migration(migrations.Migration):
    """Add the flat `agent` label scope used to group agents and shared surfaces."""

    dependencies = [
        ('tables', '0285_tool_filter_preset'),
    ]

    operations = [
        migrations.AlterField(
            model_name='label',
            name='scope',
            field=models.CharField(choices=[('flow', 'Flow'), ('tool', 'Tool'), ('agent', 'Agent')], db_index=True, default='flow', help_text='Which independent label tree this label belongs to (Flow labels and Tool labels never share instances, even with the same name/parent).', max_length=10),
        ),
        migrations.AddConstraint(
            model_name='label',
            constraint=models.CheckConstraint(condition=~models.Q(scope='agent') | models.Q(parent__isnull=True), name='agent_label_has_no_parent'),
        ),
    ]
