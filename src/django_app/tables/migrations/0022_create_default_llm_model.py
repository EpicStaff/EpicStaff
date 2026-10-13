from django.db import migrations, models

def set_default_model_in_configllm(apps, schema_editor):
    ConfigLLM = apps.get_model('tables', 'ConfigLLM')
    LLMModel = apps.get_model('tables', 'LLMModel')

    gpt4o_model = LLMModel.objects.get(name="gpt-4o")

    ConfigLLM.objects.all().update(model=gpt4o_model)

class Migration(migrations.Migration):
    dependencies = [
        ('tables', '0021_create_default_llm_model'),
    ]

    operations = [

        migrations.AddField(
            model_name='configllm',
            name='model',
            field=models.ForeignKey(
                to='tables.LLMModel',
                on_delete=models.CASCADE,
                null=True
            ),
        ),

        migrations.RunPython(set_default_model_in_configllm, elidable=True),
        
        migrations.AlterField(
            model_name='configllm',
            name='model',
            field=models.ForeignKey(
                to='tables.LLMModel',
                on_delete=models.CASCADE
            ),
        ),
    ]
