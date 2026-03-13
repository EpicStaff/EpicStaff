from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0148_merge_20260305_2121"),
    ]

    operations = [
        migrations.AlterField(
            model_name="conditionaledge",
            name="source",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.RemoveConstraint(
            model_name="conditionaledge",
            name="unique_graph_conditional_edge_source",
        ),
        migrations.AddConstraint(
            model_name="conditionaledge",
            constraint=models.UniqueConstraint(
                condition=~models.Q(source=""),
                fields=("graph", "source"),
                name="unique_graph_conditional_edge_source",
            ),
        ),
    ]
