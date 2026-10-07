from django.db.models import Q

from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.serializers.python_tools import (
    PythonCodeImportSerializer,
    PythonCodeToolConfigImportSerializer,
    PythonCodeToolImportSerializer,
)
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.utils import (
    attach_tool_labels,
    compared_values,
    create_filters,
    ensure_unique_identifier,
    filter_by_name_or_renamed_copy,
    python_code_match_q,
)
from tables.models import PythonCode, PythonCodeTool

# Scalar fields compared for reuse, next to the rename-aware name match,
# get_org_scope_q and python_code_match_q. An explicit allowlist, not
# create_filters over the whole exported dict: legacy files carry
# created_at/updated_at (and the source org), which a re-created tool never
# matches. built_in is left out because create_entity always stores False: a
# built-in whose code changed would otherwise be copied again on every import.
COMPARED_FIELDS = ("description", "variables", "use_storage")


class PythonCodeToolStrategy(EntityImportExportStrategy):
    entity_type = EntityType.PYTHON_CODE_TOOL
    serializer_class = PythonCodeToolImportSerializer

    def get_instance(self, entity_id: int) -> PythonCodeTool:
        return PythonCodeTool.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: PythonCodeTool) -> dict:
        return {"id": instance.id, "name": instance.name}

    def extract_dependencies_from_instance(self, instance) -> dict[str, list[int]]:
        return {EntityType.LABEL: list(instance.labels.values_list("id", flat=True))}

    def extract_org_scoped_dependencies(
        self, instance: PythonCodeTool, org_id: int
    ) -> dict[str, list[int]]:
        return {
            EntityType.LABEL: list(
                instance.labels.filter(org_id=org_id).values_list("id", flat=True)
            )
        }

    def export_entity(self, instance: PythonCodeTool) -> dict:
        data = self.serializer_class(instance).data
        data["labels"] = list(instance.labels.values_list("id", flat=True))
        return data

    def export_entity_org_scoped(self, instance: PythonCodeTool, org_id: int) -> dict:
        data = self.serializer_class(instance).data
        data["labels"] = list(instance.labels.filter(org_id=org_id).values_list("id", flat=True))
        return data

    def get_org_scope_q(self, org_id: int) -> Q:
        if org_id is None:
            return Q()
        return Q(built_in=True) | Q(org_id=org_id)

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> PythonCodeTool:
        org_id = kwargs.get("org_id")
        import_labels = kwargs.get("import_labels", True)
        python_code_data = data.pop("python_code", {})
        python_tool_config_data = data.pop("python_code_tool_config", [])
        labels_data = data.pop("labels", [])

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

        self._create_python_tool_config(python_code_tool, python_tool_config_data, org_id)

        if import_labels and labels_data:
            attach_tool_labels(python_code_tool, id_mapper, labels_data)

        return python_code_tool

    def find_existing(self, data, id_mapper, org_id: int | None = None):
        filters, null_filters = create_filters(
            compared_values(PythonCodeTool, data, COMPARED_FIELDS)
        )
        python_code_q = python_code_match_q(data.get("python_code"), prefix="python_code__")
        if python_code_q is None:
            return None

        # Every compared value, the code included, is filtered in SQL: a name
        # family can hold many renamed copies differing only in code, and the
        # lookup must not load them.
        return filter_by_name_or_renamed_copy(
            PythonCodeTool.objects.filter(**filters, **null_filters)
            .filter(self.get_org_scope_q(org_id))
            .filter(python_code_q),
            data.get("name"),
        ).first()

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
