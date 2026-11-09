from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone
from rbac.authorship import LAST_EDIT_TRACKER_CONTEXT_KEY, LastEditTracker
from tables.exceptions import ClassificationDecisionTableNodeNotFoundError
from tables.graph_collab.notifications import GraphEditNotifier
from tables.models.graph_models import ClassificationDecisionTableNode, Graph
from tables.serializers.model_serializers.node_serializers.flow_control_serializers import (
    ClassificationConditionGroupSectionSerializer,
    ClassificationConditionGroupSerializer,
    ClassificationDecisionTableNodeSerializer,
    ClassificationDecisionTablePromptSerializer,
)
from tables.services.classification_decision_table_node_children import (
    sync_classification_decision_table_children,
)
from tables.services.secrets.request_actor import actor_from_request
from tables.services.secrets.secret_use_checks import check_cdt_node_write


@dataclass
class ExplanationsSaveResult:
    explanations: dict
    save_version: int


class ClassificationDecisionTableNodeService:
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

        # One tracker spans the node and its children, which are synced outside the
        # serializer, so a children-only change still edits the node.
        context = {"request": request}
        last_edit_tracker = LastEditTracker(request.user) if request is not None else None
        if last_edit_tracker is not None:
            context[LAST_EDIT_TRACKER_CONTEXT_KEY] = last_edit_tracker
        serializer = ClassificationDecisionTableNodeSerializer(
            instance, data=data, partial=partial, context=context
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

        # After every validation, so a malformed payload reports its own errors first.
        check_cdt_node_write(actor_from_request(request), instance, serializer.validated_data)

        node = serializer.save()

        children_untouched = (
            partial
            and condition_groups_data is None
            and prompt_configs_data is None
            and sections_data is None
        )
        if not children_untouched:
            sync_classification_decision_table_children(
                node,
                prompt_configs_data=prompt_configs_data,
                condition_groups_data=condition_groups_data,
                sections_data=sections_data,
            )

        if last_edit_tracker is not None:
            last_edit_tracker.finish()
        return node, None if children_untouched else condition_groups_data

    @staticmethod
    def _validate_children(serializer_class, raw, request):
        """Field-level validation only; prompt resolution happens later in sync.
        Returns None if raw is None (untouched), else the validated list
        (including [] to remove all)."""
        if raw is None:
            return None
        child = serializer_class(data=raw, many=True, partial=True, context={"request": request})
        child.is_valid(raise_exception=True)
        return child.validated_data

    def save_explanations(
        self,
        node: ClassificationDecisionTableNode,
        *,
        explanations: dict,
        expected_save_version: int,
        user,
    ) -> ExplanationsSaveResult:
        """Replace the node's `metadata["explanations"]` and nothing else.

        Versioned like a bulk save: the flow's `save_version` must equal
        `expected_save_version`, and a success bumps it and tells the flow's open
        editors once the transaction commits. Every other metadata key, and every
        other field of the node, is left as stored. No version snapshot is taken.

        Args:
            node: Already resolved within the caller's organization; only its
                `pk` and `graph_id` are used.

        Raises:
            ClassificationDecisionTableNodeNotFoundError: The node was deleted meanwhile.
            GraphSaveVersionConflictError: The flow was saved since the caller loaded it.
        """
        graph_id = node.graph_id
        with transaction.atomic():
            # Graph row first, node row second: the order bulk save takes them in,
            # so the two cannot deadlock each other.
            new_save_version = Graph.increment_version_if_current(
                pk=graph_id, expected=expected_save_version
            )
            # Re-read under lock so a concurrent write to another metadata key is
            # kept rather than overwritten by the caller's copy.
            locked_node = (
                ClassificationDecisionTableNode.objects.select_for_update()
                .filter(pk=node.pk, graph_id=graph_id)
                .first()
            )
            if locked_node is None:
                raise ClassificationDecisionTableNodeNotFoundError(node.pk)
            locked_node.metadata = {**(locked_node.metadata or {}), "explanations": explanations}
            locked_node.save(update_fields=["metadata", "updated_at"])

            transaction.on_commit(
                lambda: GraphEditNotifier.notify_graph_saved(
                    graph_id=graph_id,
                    new_save_version=new_save_version,
                    user=user,
                    saved_at=timezone.now().isoformat(),
                ),
                # The save is already committed; a failed broadcast must not turn it into a 500.
                robust=True,
            )

        return ExplanationsSaveResult(explanations=explanations, save_version=new_save_version)
