from copy import deepcopy

from django.db.models import Q

from tables.models import PythonCode, PythonCodeTool
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.python_tools import (
    PythonCodeImportSerializer,
    PythonCodeToolImportSerializer,
    PythonCodeToolConfigImportSerializer,
)
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.utils import (
    ensure_unique_identifier,
    create_filters,
    python_code_equal,
)


class PythonCodeToolStrategy(EntityImportExportStrategy):
    entity_type = EntityType.PYTHON_CODE_TOOL
    serializer_class = PythonCodeToolImportSerializer

    def get_instance(self, entity_id: int) -> PythonCodeTool:
        return PythonCodeTool.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: PythonCodeTool) -> dict:
        return {"id": instance.id, "name": instance.name}

    def extract_dependencies_from_instance(self, instance) -> dict[str, list[int]]:
        return {}

    def export_entity(self, instance: PythonCodeTool) -> dict:
        return self.serializer_class(instance).data

    def get_org_scope_q(self, org_id: int) -> Q:
        if org_id is None:
            return Q()
        return Q(built_in=True) | Q(org_id=org_id)

    def create_entity(
        self, data: dict, id_mapper: IDMapper, **kwargs
    ) -> PythonCodeTool:
        org_id = kwargs.get("org_id")
        python_code_data = data.pop("python_code", {})
        python_tool_config_data = data.pop("python_code_tool_config", [])

        if "name" in data:
            existing_names = PythonCodeTool.objects.filter(org_id=org_id).values_list(
                "name", flat=True
            )
            data["name"] = ensure_unique_identifier(
                base_name=data["name"],
                existing_names=existing_names,
            )

        python_code = self._create_python_code(python_code_data)

        serializer = self.serializer_class(
            data={
                **data,
                "python_code_id": python_code.id,
                "org": org_id,
                "built_in": False,
            }
        )
        serializer.is_valid(raise_exception=True)
        python_code_tool = serializer.save()

        self._create_python_tool_config(
            python_code_tool, python_tool_config_data, org_id
        )

        return python_code_tool

    def find_existing(self, data, id_mapper, org_id: int = None):
        data_copy = deepcopy(data)
        data_copy.pop("id", None)
        data_copy.pop("python_code_tool_config", None)

        python_code_data = data_copy.pop("python_code", None)

        filters, null_filters = create_filters(data_copy)
        existing_python_tool = (
            PythonCodeTool.objects.filter(**filters, **null_filters)
            .filter(self.get_org_scope_q(org_id))
            .first()
        )

        if not existing_python_tool:
            return None

        code_equal = python_code_equal(
            existing_python_tool.python_code, python_code_data
        )
        if code_equal:
            return existing_python_tool
        return None

    def _create_python_code(self, python_code_data: dict) -> PythonCode:
        serializer = PythonCodeImportSerializer(data=python_code_data)
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def _create_python_tool_config(
        self, tool: PythonCodeTool, python_tool_config_data: dict, org_id
    ):
        for tool_config_data in python_tool_config_data:
            tool_config_data["tool_id"] = tool.id
            serializer = PythonCodeToolConfigImportSerializer(
                data={**tool_config_data, "org": org_id}
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
