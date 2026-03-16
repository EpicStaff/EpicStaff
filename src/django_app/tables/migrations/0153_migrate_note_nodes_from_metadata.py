from django.db import migrations


def migrate_note_nodes_from_metadata(apps, schema_editor):
    Graph = apps.get_model("tables", "Graph")
    NoteNode = apps.get_model("tables", "NoteNode")

    for graph in Graph.objects.all():
        metadata = graph.metadata or {}
        nodes = metadata.get("nodes", [])

        for node in nodes:
            if node.get("type") != "note":
                continue

            data = node.get("data", {})
            content = data.get("content", "")
            position = node.get("position", {})
            background_color = data.get("backgroundColor")

            note_metadata = {"position": position}
            if background_color is not None:
                note_metadata["backgroundColor"] = background_color

            NoteNode.objects.create(
                graph=graph,
                content=content,
                metadata=note_metadata,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0152_alter_conditionaledge_id"),
    ]

    operations = [
        migrations.RunPython(
            migrate_note_nodes_from_metadata,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
