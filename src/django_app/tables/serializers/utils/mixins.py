from rest_framework import serializers
from django.db.models import Model
from django.db import transaction

from tables.models.base_models import BaseGlobalNode
from tables.models.webhook_models import WebhookTrigger
from tables.models.python_models import PythonCode
from tables.services.copy_services.helpers import (
    apply_python_code_fields,
    create_python_code,
)
from tables.serializers.org_scoped_fields import (
    org_visible_queryset,
    resolve_active_org_id,
)


def assert_node_ref_in_graph(node_id, graph, field: str) -> None:
    """A node id referenced from within a graph (edge endpoints, decision-table
    next/error/condition next nodes) must belong to that SAME graph — which also
    guarantees the same organization. A cross-graph, cross-org, or non-existent
    id is rejected identically ("Invalid pk … does not exist"), so existence
    never leaks. ``graph`` may be a Graph instance or None (skips when unknown).
    """
    if node_id is None or graph is None:
        return
    node = BaseGlobalNode.find_globally(node_id)
    if node is None or getattr(node, "graph_id", None) != getattr(graph, "id", None):
        raise serializers.ValidationError(
            {field: f'Invalid pk "{node_id}" - object does not exist.'}
        )


class TagHandlingMixin:
    """
    Mixin for handling model tags.
    Rules:
    1. Predefined tags MAY be present in the request.
    2. Users CANNOT remove an existing predefined tag (validation error).
    3. Users CANNOT manually add/assign a predefined tag that was not previously present (validation error).
    """

    tag_model = None

    def _resolve_tags(self, tags_data):
        resolved = []
        for tag in tags_data:
            if "id" in tag:
                try:
                    obj = self.tag_model.objects.get(id=tag["id"])
                except self.tag_model.DoesNotExist:
                    raise serializers.ValidationError(
                        f"Tag with id {tag['id']} not found."
                    )
            elif "name" in tag:
                obj, _ = self.tag_model.objects.get_or_create(
                    name=tag["name"],
                    defaults={"predefined": False},
                )
            else:
                continue

            resolved.append(obj)
        return resolved

    def _validate_predefined_tags_on_update(self, instance, resolved_tags):
        resolved_set = set(resolved_tags)
        existing_predefined = set(instance.tags.filter(predefined=True))

        missing_tags = existing_predefined - resolved_set
        if missing_tags:
            names = ", ".join([t.name for t in missing_tags])
            raise serializers.ValidationError(
                f"You cannot remove the following predefined tags: {names}. They must be present in the request."
            )

        incoming_predefined = {t for t in resolved_set if t.predefined}
        new_predefined = incoming_predefined - existing_predefined
        if new_predefined:
            names = ", ".join([t.name for t in new_predefined])
            raise serializers.ValidationError(
                f"You cannot manually assign predefined tags: {names}."
            )

    def _validate_predefined_tags_on_create(self, resolved_tags):
        for tag in resolved_tags:
            if tag.predefined:
                raise serializers.ValidationError(
                    f"You cannot manually assign predefined tag '{tag.name}' during creation."
                )

    def create(self, validated_data):
        tags_data = validated_data.pop("tags", [])
        instance = super().create(validated_data)
        if tags_data:
            resolved_tags = self._resolve_tags(tags_data)
            self._validate_predefined_tags_on_create(resolved_tags)
            instance.tags.set(resolved_tags)
        return instance

    def update(self, instance, validated_data):
        tags_data = validated_data.pop("tags", None)
        if tags_data is not None:
            resolved_tags = self._resolve_tags(tags_data)
            self._validate_predefined_tags_on_update(instance, resolved_tags)
            instance.tags.set(resolved_tags)
        return super().update(instance, validated_data)


class NestedPythonCodeMixin:
    def _create_with_python_code(self, model_class, validated_data):
        python_code_data = validated_data.pop("python_code")
        python_code = create_python_code(python_code_data=python_code_data)
        return model_class.objects.create(python_code=python_code, **validated_data)

    def _update_python_code(self, instance, validated_data):
        python_code_data = validated_data.pop("python_code", None)
        if python_code_data:
            python_code = instance.python_code
            expected_hash = python_code_data.pop("content_hash", None)
            if expected_hash is not None:
                python_code._expected_hash = expected_hash
            apply_python_code_fields(
                python_code=python_code, python_code_data=python_code_data
            )

    def create(self, validated_data):
        return self._create_with_python_code(self.Meta.model, validated_data)

    def update(self, instance, validated_data):
        self._update_python_code(instance, validated_data)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        return instance

    def partial_update(self, instance, validated_data):
        return self.update(instance, validated_data)


class ToolsConnectionMixin:
    def _resolve_tool_ids(self, tool_ids: list[str]) -> dict[str, list[str]]:
        """
        Resolve tool ids from 'prefix:id' format to map {prefix: [id1, id2, ...]}
        """
        result: dict[str, list[str]] = {}
        for tool_id in tool_ids:
            try:
                prefix, pk = tool_id.split(":")
                result.setdefault(prefix, []).append(pk)
            except Exception as e:
                raise serializers.ValidationError({"tool_ids": str(e)})
        return result

    def _get_tools_models_map(self) -> dict[type[Model], tuple[type[Model], str, str]]:
        """
        Return mapping for tool synchronization.

        Key:
            Tool model class (e.g. PythonCodeTool)

        Value:
            tuple:
                - through model class (e.g. TaskPythonCodeTools)
                - tool prefix used in tool_ids (e.g. "python-code-tool")
                - FK field name in through model (e.g. "tool_id")
        """
        raise NotImplementedError

    def validate_tool_ids(self, value: list[str]) -> list[str]:
        """Fail-fast org-isolation check on `tool_ids` (runs in is_valid(),
        before any row is written). A tool from another org — or a non-existent
        one — is rejected exactly like a missing pk, no existence leak. Skipped
        when there is no request in context (import / internal paths)."""
        request = self.context.get("request")
        if request is None or not value:
            return value

        org_id = resolve_active_org_id(request)
        tools_dict = self._resolve_tool_ids(value)
        prefix_to_model = {
            prefix: model
            for model, (_through, prefix, _fk) in self._get_tools_models_map().items()
        }
        for prefix, ids in tools_dict.items():
            model = prefix_to_model.get(prefix)
            if model is None:
                raise serializers.ValidationError(
                    {"tool_ids": [f'Unknown tool type "{prefix}".']}
                )
            visible = {
                str(pk)
                for pk in org_visible_queryset(model, org_id)
                .filter(id__in=ids)
                .values_list("id", flat=True)
            }
            missing = [str(i) for i in ids if str(i) not in visible]
            if missing:
                raise serializers.ValidationError(
                    {
                        "tool_ids": [
                            f'Invalid pk "{prefix}:{m}" - object does not exist.'
                            for m in missing
                        ]
                    }
                )
        return value

    def _sync_tools(self, instance: Model, fk_to_instance: str, tool_ids: list[str]):
        """
        Synchronize tools for an instance.

        Deletes existing tool relations and creates new ones
        based on the provided tool IDs.

        Args:
            instance (Model): Instance to link tools with.
            fk_to_instance (str): FK field name in through model pointing to instance (e.g. "task_id").
            tool_ids (list[str]): List of tool ids in format "prefix:id".
        """
        tools_dict = self._resolve_tool_ids(tool_ids)
        tools_map = self._get_tools_models_map()

        # Resolve the active org so a tool from another org can't be attached
        request = self.context.get("request")
        org_id = resolve_active_org_id(request) if request is not None else None

        with transaction.atomic():
            for tool_model, (through_model, prefix, fk_field) in tools_map.items():
                through_model.objects.filter(**{fk_to_instance: instance.pk}).delete()

                ids = tools_dict.get(prefix)
                if not ids:
                    continue

                # Defense in depth: only link tools visible to the active org
                # (validate_tool_ids already rejected cross-org ids on the API
                # path; this also protects any non-validated caller)
                base = (
                    org_visible_queryset(tool_model, org_id)
                    if org_id is not None
                    else tool_model.objects.all()
                )
                db_ids = list(base.filter(id__in=ids).values_list("id", flat=True))

                through_model.objects.bulk_create(
                    [
                        through_model(**{fk_to_instance: instance.pk, fk_field: pk})
                        for pk in db_ids
                    ]
                )


class WebhookCreationMixin:
    def _get_or_create_webhook_trigger(self, data):
        path = data.get("path")
        ngrok_conf = data.get("ngrok_webhook_config")

        # ngrok_webhook_config is global platform infrastructure managed by
        # superadmins (the /api/ngrok-config/ endpoint is superadmin-only). Non-
        # superadmins may not assign it via a webhook-trigger node either — drop
        # it so a caller can't bind an arbitrary config by id.
        #
        # TODO: TECH DEBT (per-org ngrok): NgrokWebhookConfig has no `org` column, so
        # this is a superadmin gate rather than org scoping. To make webhook
        # tunnels per-organization, add an `org` FK to NgrokWebhookConfig, scope
        # it, and replace this gate with OrgScopedPrimaryKeyRelatedField.
        request = self.context.get("request")
        is_superadmin = getattr(getattr(request, "user", None), "is_superadmin", False)
        if not is_superadmin:
            ngrok_conf = None

        return WebhookTrigger.objects.get_or_create(
            path=path, ngrok_webhook_config=ngrok_conf
        )
