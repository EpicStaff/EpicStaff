from tables.models.label_models import Label
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


def attach_tool_labels(instance, id_mapper: IDMapper, label_ids: list) -> None:
    """Attach previously-exported tool labels to a freshly-imported tool instance.

    Mirrors ``GraphStrategy._attach_labels`` (import_export/strategies/graph.py)
    but scoped to ``Label.Scope.TOOL`` instead of ``Scope.FLOW`` — shared between
    ``PythonCodeToolStrategy`` and ``McpToolStrategy`` since both need identical
    logic.
    """
    new_label_ids = [id_mapper.get(EntityType.LABEL, old_id) for old_id in label_ids]
    if new_label_ids:
        instance.labels.add(
            *Label.objects.filter(id__in=new_label_ids, scope=Label.Scope.TOOL)
        )
