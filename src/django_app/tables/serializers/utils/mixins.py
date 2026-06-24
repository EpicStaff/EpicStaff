from rest_framework import serializers
from django.db.models import Model
from django.db import transaction

from tables.models.webhook_models import (
    LocalhostWebhookConfig,
    NgrokWebhookConfig,
    ProviderType,
    WebhookTrigger,
)
from tables.models.python_models import PythonCode
from tables.models import Agent, PythonCodeTool, ToolConfig, McpTool
from utils.logger import logger


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
        python_code = PythonCode.objects.create(**python_code_data)
        return model_class.objects.create(python_code=python_code, **validated_data)

    def _update_python_code(self, instance, validated_data):
        python_code_data = validated_data.pop("python_code", None)
        if python_code_data:
            python_code = instance.python_code
            expected_hash = python_code_data.pop("content_hash", None)
            if expected_hash is not None:
                python_code._expected_hash = expected_hash
            for attr, value in python_code_data.items():
                setattr(python_code, attr, value)
            python_code.save()

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

        with transaction.atomic():
            for tool_model, (through_model, prefix, fk_field) in tools_map.items():
                through_model.objects.filter(**{fk_to_instance: instance.pk}).delete()

                ids = tools_dict.get(prefix)
                if not ids:
                    continue

                db_ids = tool_model.objects.filter(id__in=ids).values_list(
                    "id", flat=True
                )

                through_model.objects.bulk_create(
                    [
                        through_model(**{fk_to_instance: instance.pk, fk_field: pk})
                        for pk in db_ids
                    ]
                )


class WebhookCreationMixin:
    @transaction.atomic
    def _get_or_create_webhook_trigger(self, data):
        path = data.get("path")
        provider_type = data.get("provider_type")

        try:
            trigger = WebhookTrigger.objects.get(path=path)
            created = False
        except WebhookTrigger.DoesNotExist:
            trigger = WebhookTrigger.objects.create(
                path=path, provider_type=provider_type
            )
            created = True
        except WebhookTrigger.MultipleObjectsReturned:
            logger.warning(
                "Multiple WebhookTrigger rows found for path=%r — "
                "expected at most one. Using the first result.",
                path,
            )
            trigger = WebhookTrigger.objects.filter(path=path).first()
            if trigger is None:
                raise serializers.ValidationError(
                    f"WebhookTrigger with path={path!r} disappeared during lookup."
                )
            created = False

        if not created and trigger.provider_type != provider_type:
            # Provider changed — delete the old config to avoid orphan
            if trigger.provider_type == ProviderType.NGROK:
                NgrokWebhookConfig.objects.filter(trigger=trigger).delete()
            elif trigger.provider_type == ProviderType.LOCALHOST:
                LocalhostWebhookConfig.objects.filter(trigger=trigger).delete()
            trigger.provider_type = provider_type
            trigger.save(update_fields=["provider_type"])

        if provider_type == ProviderType.NGROK:
            ngrok_data = data.get("ngrok_config")
            if ngrok_data:
                NgrokWebhookConfig.objects.update_or_create(
                    trigger=trigger, defaults=ngrok_data
                )
        elif provider_type == ProviderType.LOCALHOST:
            localhost_data = data.get("localhost_config")
            if localhost_data:
                LocalhostWebhookConfig.objects.update_or_create(
                    trigger=trigger, defaults=localhost_data
                )

        return trigger, created


class WebhookTriggerIntRefMixin:
    """Accept webhook_trigger as an integer PK in addition to a nested dict.

    Stores the raw PK in _webhook_trigger_id during to_internal_value so that
    create/update can resolve it without re-running nested validation.
    """

    def to_internal_value(self, data):
        wt = data.get("webhook_trigger")
        if isinstance(wt, int):
            self._webhook_trigger_id = wt
            data = data.copy()
            data["webhook_trigger"] = None
        else:
            self._webhook_trigger_id = None
        return super().to_internal_value(data)

    def _apply_webhook_trigger_fk_to_create(self, validated_data: dict) -> bool:
        """Set validated_data['webhook_trigger'] from int PK if one was supplied.

        Returns True if the PK branch was taken so callers can skip the
        nested-dict branch.
        """
        wt_id = getattr(self, "_webhook_trigger_id", None)
        if wt_id:
            validated_data["webhook_trigger"] = WebhookTrigger.objects.filter(
                id=wt_id
            ).first()
            return True
        return False

    def _apply_webhook_trigger_fk_to_update(
        self, instance, validated_data: dict
    ) -> bool:
        """Set instance.webhook_trigger from int PK if one was supplied.

        Returns True if the PK branch was taken so callers can skip the
        nested-dict branch.
        """
        wt_id = getattr(self, "_webhook_trigger_id", None)
        if wt_id:
            instance.webhook_trigger = WebhookTrigger.objects.filter(id=wt_id).first()
            validated_data.pop("webhook_trigger", None)
            return True
        return False
