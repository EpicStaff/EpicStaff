# Generated manually for EST-2186

from collections import defaultdict

from django.db import migrations, models


def rename_duplicate_graph_names(apps, schema_editor):
    Graph = apps.get_model("tables", "Graph")

    name_groups = defaultdict(list)
    for graph in Graph.objects.order_by("id"):
        name_groups[graph.name].append(graph)

    for original_name, graphs in name_groups.items():
        if len(graphs) <= 1:
            continue

        counter = 1
        for graph in graphs[1:]:
            candidate = f"{original_name} ({counter})"
            while Graph.objects.filter(name=candidate).exists():
                counter += 1
                candidate = f"{original_name} ({counter})"
            graph.name = candidate
            graph.save()
            counter += 1


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0149_ngrokwebhookconfig_and_more"),
    ]

    operations = [
        migrations.RunPython(
            rename_duplicate_graph_names,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="graph",
            name="name",
            field=models.CharField(max_length=255, unique=True),
        ),
    ]
