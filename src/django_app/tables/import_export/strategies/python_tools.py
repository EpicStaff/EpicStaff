from django.db.models import Q

from tables.import_export.constants import MAX_REUSE_CANDIDATES
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
    import_values,
)
from tables.models import PythonCode, PythonCodeTool

# Scalar fields compared for reuse, next to the rename-aware name match,
# get_org_scope_q and python_code_key. An explicit allowlist, not
# create_filters over the whole exported dict: legacy files carry
# created_at/updated_at (and the source org), which a re-created tool never
# matches. built_in is left out because create_entity always stores False: a
# built-in whose code changed would otherwise be copied again on every import.
COMPARED_FIELDS = ("description", "variables", "use_storage")


def python_code_key(code: str, libraries: str, entrypoint: str) -> tuple:
    """Return what python code is matched on, from file values or a stored row.

    File values arrive as PythonCodeImportSerializer stores them (trimmed, an
    empty entrypoint made "main"). A stored row is compared as it would run:
    only trailing whitespace is ignored in code, since the sandbox indents
    every line and leading whitespace changes it; libraries split on spaces;
    the entrypoint must be exact.
    """
    return (code.rstrip(), libraries.strip(), entrypoint)


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
        # SQL narrows on stored columns: entrypoint and global_kwargs exactly
        # (create stores them so, and jsonb equality keeps true apart from 1).
        # Code and libraries are compared in Python.
        filters, null_filters = create_filters(
            compared_values(PythonCodeTool, self.serializer_class, data, COMPARED_FIELDS)
        )
        python_code = self.validated_python_code(data.get("python_code"))
        code_key = python_code_key(
            python_code["code"], python_code["libraries"], python_code["entrypoint"]
        )
        candidates = filter_by_name_or_renamed_copy(
            PythonCodeTool.objects.filter(**filters, **null_filters)
            .filter(
                self.get_org_scope_q(org_id),
                python_code__entrypoint=code_key[2],
                python_code__global_kwargs=python_code["global_kwargs"],
            )
            .select_related("python_code"),
            import_values(self.serializer_class, data, ("name",)).get("name"),
        )[:MAX_REUSE_CANDIDATES]
        return next(
            (
                candidate
                for candidate in candidates
                if python_code_key(
                    candidate.python_code.code,
                    candidate.python_code.libraries,
                    candidate.python_code.entrypoint,
                )
                == code_key
            ),
            None,
        )

    @staticmethod
    def validated_python_code(python_code_data: dict) -> dict:
        """Return exported python code as create would store it, defaults filled in."""
        serializer = PythonCodeImportSerializer(data=python_code_data)
        serializer.is_valid(raise_exception=True)
        return {
            "global_kwargs": PythonCode._meta.get_field("global_kwargs").get_default(),
            **serializer.validated_data,
        }

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
