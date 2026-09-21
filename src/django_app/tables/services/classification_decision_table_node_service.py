import json
from dataclasses import dataclass

from rest_framework.exceptions import ValidationError as DRFValidationError

from tables.exceptions import ClassificationDecisionTableNodeNotFoundError
from tables.models.graph_models import ClassificationDecisionTableNode
from tables.serializers.model_serializers.node_serializers.flow_control_serializers import (
    ClassificationDecisionTableNodeSerializer,
    ClassificationDecisionTablePromptSerializer,
    ClassificationConditionGroupSerializer,
    ClassificationConditionGroupSectionSerializer,
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
        raw_sections = data.pop("sections", None)
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
        sections_data = self._validate_children(
            serializer_class=ClassificationConditionGroupSectionSerializer,
            raw=raw_sections,
            request=request,
        )
        condition_groups_data = self._validate_children(
            serializer_class=ClassificationConditionGroupSerializer,
            raw=raw_condition_groups,
            request=request,
        )

        node = serializer.save()

        if (
            partial
            and condition_groups_data is None
            and prompt_configs_data is None
            and sections_data is None
        ):
            return node, None

        sync_classification_decision_table_children(
            node,
            prompt_configs_data=prompt_configs_data,
            condition_groups_data=condition_groups_data,
            sections_data=sections_data,
        )

        return node, condition_groups_data

    @staticmethod
    def _validate_children(serializer_class, raw, request):
        """Field-level validation only; prompt resolution happens later in sync.
        Returns None if raw is None (untouched), else the validated list
        (including [] to remove all)."""
        if raw is None:
            return None
        child = serializer_class(
            data=raw, many=True, partial=True, context={"request": request}
        )
        child.is_valid(raise_exception=True)
        return child.validated_data

    @staticmethod
    def _get_node_or_404(pk, org_id: int, *, select_related: str | None = None):
        """Fetch the node scoped to org_id (bypasses viewset scoping). Cross-org
        and nonexistent ids both 404 (no leak)."""
        qs = ClassificationDecisionTableNode.objects.filter(pk=pk, graph__org_id=org_id)
        if select_related:
            qs = qs.select_related(select_related)
        node = qs.first()
        if node is None:
            raise ClassificationDecisionTableNodeNotFoundError(pk)
        return node

    def export(
        self, pk, export_format: str = "json", *, org_id: int
    ) -> NodeExportResult:
        export_format = (export_format or "json").lower()
        if export_format not in ("json", "csv"):
            raise DRFValidationError(
                {"export_format": "Unsupported format. Use 'json' or 'csv'."}
            )

        if export_format == "csv":
            node = self._get_node_or_404(
                pk, org_id, select_related="default_llm_config__model"
            )
            buf = export_condition_groups_csv(node)
            return NodeExportResult(
                content=buf.getvalue(),
                content_type="text/csv",
                filename=f"CDT_{node.node_name}.csv",
            )

        # JSON: reuse the partial-export pipeline so the file is identical in
        # structure to a partial export (and re-importable via partial-import).
        node = self._get_node_or_404(pk, org_id)
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
