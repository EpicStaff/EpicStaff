from django.db.models import Q
from rbac.authorship import resolve_author

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
    python_code_venv_ids,
    remap_python_code_venv,
)
from tables.models import PythonCode, PythonCodeTool, User
from tables.serializers.utils.description_sanitizer import sanitize_description

# Scalar fields compared for reuse, next to the rename-aware name match,
# get_org_scope_q and python_code_key. An explicit allowlist, not
# create_filters over the whole exported dict: legacy files carry
# created_at/updated_at (and the source org), which a re-created tool never
# matches. built_in is left out because create_entity always stores False: a
# built-in whose code changed would otherwise be copied again on every import.
COMPARED_FIELDS = ("description", "variables", "use_storage")


def python_code_key(code: str, venv_id: int | None, entrypoint: str) -> tuple:
    """Return what python code is matched on, from file values or a stored row.

    File values arrive as PythonCodeImportSerializer stores them (trimmed, an
    empty entrypoint made "main") and with `venv_id` already remapped to a local
    binding. A stored row is compared as it would run: only trailing whitespace is
    ignored in code, since the sandbox indents every line and leading whitespace
    changes it; the venv and the entrypoint must be exact. The venv stands in for
    the libraries the code used to carry -- it is the only place they live now.
    """
    return (code.rstrip(), venv_id, entrypoint)


class PythonCodeToolStrategy(EntityImportExportStrategy):
    entity_type = EntityType.PYTHON_CODE_TOOL
    serializer_class = PythonCodeToolImportSerializer

    def get_instance(self, entity_id: int) -> PythonCodeTool:
        return PythonCodeTool.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: PythonCodeTool) -> dict:
        return {"id": instance.id, "name": instance.name}

    def extract_dependencies_from_instance(self, instance) -> dict[str, list[int]]:
        return {
            EntityType.LABEL: list(instance.labels.values_list("id", flat=True)),
            EntityType.VENV: python_code_venv_ids(instance.python_code),
        }

    def extract_org_scoped_dependencies(
        self, instance: PythonCodeTool, org_id: int
    ) -> dict[str, list[int]]:
        return {
            EntityType.LABEL: list(
                instance.labels.filter(org_id=org_id).values_list("id", flat=True)
            ),
            EntityType.VENV: python_code_venv_ids(instance.python_code, org_id=org_id),
        }

    def export_entity(self, instance: PythonCodeTool) -> dict:
        """Export the tool without configs: with no org known, none can be attributed to the caller."""
        data = self.serializer_class(instance).data
        data["labels"] = list(instance.labels.values_list("id", flat=True))
        return data

    def export_entity_org_scoped(self, instance: PythonCodeTool, org_id: int) -> dict:
        data = self.serializer_class(instance, context={"org_id": org_id}).data
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

        python_code = self._create_python_code(python_code_data, id_mapper)

        serializer = self.serializer_class(
            data={
                **data,
                "python_code_id": python_code.id,
                "org": org_id,
                "built_in": False,
            }
        )
        serializer.is_valid(raise_exception=True)
        author = resolve_author(kwargs.get("user"))
        python_code_tool = serializer.save(created_by=author)

        self._create_python_tool_config(
            python_code_tool, python_tool_config_data, org_id, author=author
        )

        if import_labels and labels_data:
            attach_tool_labels(python_code_tool, id_mapper, labels_data)

        return python_code_tool

    def find_existing(self, data, id_mapper, org_id: int | None = None):
        # SQL narrows on stored columns: venv, entrypoint, global_kwargs and
        # execution_timeout exactly (create stores them so, and jsonb equality
        # keeps true apart from 1). Only the code itself is compared in Python.
        # Description is compared cleaned on both sides: create stores it
        # sanitized, but a built-in tool keeps upload_tools' text, which can exceed
        # the sanitizer's cap. Org rows still narrow on it in SQL (as written or
        # cleaned), so tools that differ only in description never crowd the right
        # one out of the candidate window.
        compared = compared_values(PythonCodeTool, self.serializer_class, data, COMPARED_FIELDS)
        description = compared.pop("description", None)
        filters, null_filters = create_filters(compared)
        description_q = Q()
        if description is not None:
            stored_forms = [description, sanitize_description(description)]
            description_q = Q(description__in=stored_forms) | Q(built_in=True)
        python_code = self.validated_python_code(
            remap_python_code_venv(data.get("python_code"), id_mapper)
        )
        code_key = python_code_key(
            python_code["code"], python_code["venv_id"], python_code["entrypoint"]
        )
        candidates = filter_by_name_or_renamed_copy(
            PythonCodeTool.objects.filter(**filters, **null_filters)
            .filter(
                description_q,
                self.get_org_scope_q(org_id),
                python_code__venv_id=code_key[1],
                python_code__entrypoint=code_key[2],
                python_code__global_kwargs=python_code["global_kwargs"],
                python_code__execution_timeout=python_code["execution_timeout"],
            )
            .select_related("python_code"),
            import_values(self.serializer_class, data, ("name",)).get("name"),
        )[:MAX_REUSE_CANDIDATES]
        matches = [
            candidate
            for candidate in candidates
            if python_code_key(
                candidate.python_code.code,
                candidate.python_code.venv_id,
                candidate.python_code.entrypoint,
            )
            == code_key
            and (
                description is None
                or sanitize_description(candidate.description) == sanitize_description(description)
            )
        ]
        # A tool stored with the file's exact text wins over one that matches only
        # once cleaned, so a built-in stays the tool reused.
        exact_match = next(
            (candidate for candidate in matches if candidate.description == description), None
        )
        return exact_match or (matches[0] if matches else None)

    @staticmethod
    def validated_python_code(python_code_data: dict) -> dict:
        """Return exported python code as create would store it, defaults filled in."""
        serializer = PythonCodeImportSerializer(data=python_code_data)
        serializer.is_valid(raise_exception=True)
        return {
            "global_kwargs": PythonCode._meta.get_field("global_kwargs").get_default(),
            "venv_id": None,
            "execution_timeout": PythonCode._meta.get_field("execution_timeout").get_default(),
            **serializer.validated_data,
        }

    def _create_python_code(self, python_code_data: dict, id_mapper: IDMapper) -> PythonCode:
        serializer = PythonCodeImportSerializer(
            data=remap_python_code_venv(python_code_data, id_mapper)
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def _create_python_tool_config(
        self, tool: PythonCodeTool, python_tool_config_data: dict, org_id, *, author: User | None
    ):
        for tool_config_data in python_tool_config_data:
            tool_config_data["tool_id"] = tool.id
            serializer = PythonCodeToolConfigImportSerializer(
                data={**tool_config_data, "org": org_id}
            )
            serializer.is_valid(raise_exception=True)
            serializer.save(created_by=author)
