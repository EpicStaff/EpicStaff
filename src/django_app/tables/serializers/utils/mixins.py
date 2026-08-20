from rest_framework import serializers
from django.db.models import Model
from django.db import transaction

from tables.models.base_models import BaseGlobalNode
from tables.models.python_models import PythonCode
from tables.models import Agent, PythonCodeTool, ToolConfig, McpTool
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


class NestedAgentExportMixin:
    """
    A mixin that defines methods for exporting `Agent` fields data when
    agent is being used as part of another entity in serializer.

    Feilds that can be defined in a child class:
        `tools`: dictionary where `key` is tools name and `value` is list of tool IDs
        `llm_config`: integer field
        `fcm_llm_config`: integer field
        `realtime_agent`: integer field

    Methods:
        `get_tools`: returns lists of IDs for each tool type that agent has in database
        `get_llm_config`: returns an ID of agent's LLMConfig
        `get_fcm_llm_config`: returns an ID of agent's FCM LLMConfig
        `get_realtime_agent`: returns an ID of realtime agent that is related to agent
    """

    def get_tools(self, agent):
        return {
            "python_tools": list(
                PythonCodeTool.objects.filter(
                    agentpythoncodetools__agent_id=agent.pk
                ).values_list("id", flat=True)
            ),
            "configured_tools": list(
                ToolConfig.objects.filter(
                    agentconfiguredtools__agent_id=agent.pk
                ).values_list("id", flat=True)
            ),
            "mcp_tools": list(
                McpTool.objects.filter(agentmcptools__agent_id=agent.pk).values_list(
                    "id", flat=True
                )
            ),
        }

    def get_llm_config(self, agent: Agent):
        if agent.llm_config:
            return agent.llm_config.id

    def get_fcm_llm_config(self, agent: Agent):
        if agent.fcm_llm_config:
            return agent.fcm_llm_config.id

    def get_realtime_agent(self, agent: Agent):
        if agent.realtime_agent:
            return agent.realtime_agent.pk


class NestedCrewExportMixin:
    """
    A mixin that defines methods for exporting `Crew` fields data when
    crew is being used as part of another entity in serializer.

    Feilds that can be defined in a child class:
        `agents`: a list of integers

    Methods:
        `get_ageants`: returns a list of agent IDs for this crew
    """

    def get_agents(self, crew):
        agents = list(crew.agents.all().values_list("id", flat=True))
        return agents


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
            Tool model class (e.g. ToolConfig)

        Value:
            tuple:
                - through model class (e.g. TaskConfiguredTools)
                - tool prefix used in tool_ids (e.g. "configured-tool")
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


