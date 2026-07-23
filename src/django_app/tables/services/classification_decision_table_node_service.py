import json
from dataclasses import dataclass

from rest_framework.exceptions import ValidationError as DRFValidationError

from tables.models.graph_models import ClassificationDecisionTableNode
from tables.serializers.model_serializers.node_serializers.flow_control_serializers import (
    ClassificationDecisionTableNodeSerializer,
    ClassificationDecisionTablePromptSerializer,
    ClassificationConditionGroupSerializer,
)
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.export_tabular_projections.export_classification_decision_table_csv import (
    export_condition_groups_csv,
)
from tables.utils.helpers import generate_file_name
from tables.services.classification_decision_table_node_children import (
    sync_classification_decision_table_children,
)


@dataclass
class NodeExportResult:
    """Payload for the view to turn into an HTTP response."""

    content: str | None = None
    content_type: str | None = None
    filename: str | None = None
    errors: list | None = None


class ClassificationDecisionTableNodeService:
    def __init__(self):
        self._partial_export_service = GraphPartialExportService(entity_registry)

    def create_or_update(
        self,
        data: dict,
        instance: ClassificationDecisionTableNode | None = None,
        partial: bool = False,
        *,
        request=None,
    ) -> tuple[ClassificationDecisionTableNode, list | None]:
        data = data.copy()
        raw_condition_groups = data.pop("condition_groups", None)
        raw_prompt_configs = data.pop("prompt_configs", None)

        serializer = ClassificationDecisionTableNodeSerializer(
            instance, data=data, partial=partial, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        prompt_configs_data = self._validate_children(
            serializer_class=ClassificationDecisionTablePromptSerializer,
            raw=raw_prompt_configs,
            request=request,
        )
        condition_groups_data = self._validate_children(
            serializer_class=ClassificationConditionGroupSerializer,
            raw=raw_condition_groups,
            request=request,
        )

        node = serializer.save()

        if partial and condition_groups_data is None and prompt_configs_data is None:
            return node, None

        sync_classification_decision_table_children(
            node,
            prompt_configs_data=prompt_configs_data,
            condition_groups_data=condition_groups_data,
        )

        return node, condition_groups_data

    @staticmethod
    def _validate_children(serializer_class, raw, request):
        """Field-level validation only (blank group_name, org-scoped llm_config),
        run before the node is saved; node-local prompt resolution happens later
        in sync_classification_decision_table_children, once sibling prompts
        actually exist. Returns None if raw is None (key absent - untouched) or
        the validated list otherwise, including [] (remove all) - sync tells the
        two apart."""
        if raw is None:
            return None
        child = serializer_class(
            data=raw, many=True, partial=True, context={"request": request}
        )
        child.is_valid(raise_exception=True)
        return child.validated_data

    def export(self, pk, export_format: str = "json") -> NodeExportResult:
        export_format = (export_format or "json").lower()
        if export_format not in ("json", "csv"):
            raise DRFValidationError(
                {"export_format": "Unsupported format. Use 'json' or 'csv'."}
            )

        if export_format == "csv":
            node = ClassificationDecisionTableNode.objects.select_related(
                "default_llm_config__model"
            ).get(pk=pk)
            buf = export_condition_groups_csv(node)
            return NodeExportResult(
                content=buf.getvalue(),
                content_type="text/csv",
                filename=f"CDT_{node.node_name}.csv",
            )

        # JSON: reuse the partial-export pipeline so the file is identical in
        # structure to a partial export (and re-importable via partial-import).
        node = ClassificationDecisionTableNode.objects.get(pk=pk)
        result = self._partial_export_service.export(
            [
                NodeRef(
                    entity_type=EntityType.CLASSIFICATION_DECISION_TABLE_NODE,
                    node_id=node.id,
                )
            ]
        )
        if result.has_errors:
            return NodeExportResult(errors=result.errors)

        return NodeExportResult(
            content=json.dumps(result.data, indent=4),
            content_type="application/json",
            filename=generate_file_name(f"{node.node_name}", prefix="CDT"),
        )
