# Generated by Django 5.1.3 on 2025-03-21 14:25

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tables', '0066_realtimeagent'),
    ]

    operations = [
        migrations.CreateModel(
            name='RealtimeAgentModel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rt_model_name', models.CharField(default='gpt-4o-mini-realtime-preview-2024-12-17', max_length=250)),
            ],
        ),
        migrations.AddField(
            model_name='realtimeagent',
            name='model',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='tables.realtimeagentmodel'),
        ),
    ]
