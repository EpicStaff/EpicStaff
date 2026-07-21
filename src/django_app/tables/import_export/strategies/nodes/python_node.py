from typing import Optional

from tables.models import PythonNode
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.python_node import PythonNodeImportSerializer
from tables.import_export.serializers.python_tools import PythonCodeImportSerializer
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


class PythonNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.PYTHON_NODE
    serializer_class = PythonNodeImportSerializer

    def get_instance(self, entity_id: int) -> Optional[PythonNode]:
        return PythonNode.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: PythonNode) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(self, instance: PythonNode) -> dict:
        return {EntityType.GRAPH: [instance.graph_id]}

    def export_entity(self, instance: PythonNode) -> dict:
        return self.serializer_class(instance).data

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> PythonNode:
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))
        python_code_data = data.pop("python_code", None)

        python_code_serializer = PythonCodeImportSerializer(data=python_code_data)
        python_code_serializer.is_valid(raise_exception=True)
        python_code = python_code_serializer.save()

        serializer = self.serializer_class(
            data={**data, "graph": graph_id, "python_code_id": python_code.id}
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()
