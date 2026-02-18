from django.db import migrations
from django.db.models import Count

def remove_duplicates(apps, schema_editor):
    LLMModel = apps.get_model("tables", "LLMModel")
    EmbeddingModel = apps.get_model("tables", "EmbeddingModel")

    duplicates_llm = (
        LLMModel.objects.values('name', 'llm_provider')
        .annotate(count=Count('id'))
        .filter(count__gt=1)
    )

    for entry in duplicates_llm:
        name = entry['name']
        provider = entry['llm_provider']
        qs = LLMModel.objects.filter(name=name, llm_provider=provider)
        keep_obj = qs.first()
        if keep_obj:
            qs.exclude(pk=keep_obj.pk).delete()

    duplicates_emb = (
        EmbeddingModel.objects.values('name', 'embedding_provider')
        .annotate(count=Count('id'))
        .filter(count__gt=1)
    )

    for entry in duplicates_emb:
        name = entry['name']
        provider = entry['embedding_provider']
        qs = EmbeddingModel.objects.filter(name=name, embedding_provider=provider)
        keep_obj = qs.first()
        if keep_obj:
            qs.exclude(pk=keep_obj.pk).delete()


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("tables", "0138_embeddingmodeltag_llmconfigtag_llmmodeltag_and_more"),
    ]

    operations = [
        migrations.RunPython(remove_duplicates, reverse_code=migrations.RunPython.noop),
        
        migrations.AlterUniqueTogether(
            name="embeddingmodel",
            unique_together={("name", "embedding_provider")},
        ),
        migrations.AlterUniqueTogether(
            name="llmmodel",
            unique_together={("name", "llm_provider")},
        ),
    ]