import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Group agents and shared surfaces under an agent-scope label.

    SET_NULL: deleting a group un-groups its items and never deletes them.
    """

    dependencies = [
        ('agents', '0016_recycle_bin_soft_delete'),
        ('tables', '0286_label_agent_scope'),
    ]

    operations = [
        migrations.AddField(
            model_name='agentdefinition',
            name='group',
            field=models.ForeignKey(blank=True, help_text='Agent-scope label this agent is grouped under. Null means ungrouped; deleting the group un-groups the agent.', limit_choices_to={'scope': 'agent'}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='agent_definitions', to='tables.label'),
        ),
        migrations.AddField(
            model_name='surface',
            name='group',
            field=models.ForeignKey(blank=True, help_text='Agent-scope label this shared surface is grouped under. Only shared surfaces (no owner_agent) may be grouped; deleting the group un-groups the surface.', limit_choices_to={'scope': 'agent'}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='surfaces', to='tables.label'),
        ),
        migrations.AddConstraint(
            model_name='surface',
            constraint=models.CheckConstraint(condition=models.Q(owner_agent__isnull=True) | models.Q(group__isnull=True), name='surface_group_only_when_shared'),
        ),
    ]
