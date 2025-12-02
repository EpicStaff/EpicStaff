from typing import Any, Literal
from decimal import Decimal
from itertools import chain

from tables.models.webhook_models import WebhookTrigger
from tables.models.graph_models import WebhookTriggerNode
from tables.models.mcp_models import McpTool
from tables.models.knowledge_models import Chunk, DocumentMetadata
from tables.serializers.serializers import BaseToolSerializer
from tables.models import (
    Agent,
    Task,
    TaskContext,
    TaskConfiguredTools,
    TemplateAgent,
    Tool,
    ToolConfigField,
)
from tables.models import LLMConfig
from tables.models import EmbeddingConfig
from tables.models import EmbeddingModel
from tables.models import LLMModel
from tables.models import Provider
from tables.models import Crew
from tables.models import (
    ConditionalEdge,
    CrewNode,
    Edge,
    Graph,
    GraphSessionMessage,
    PythonNode,
    FileExtractorNode,
    SubGraphNode,
    AudioTranscriptionNode,
    GraphFile,
)
from rest_framework import serializers
from tables.exceptions import BuiltInToolModificationError, ToolConfigSerializerError
from tables.models import PythonCode, PythonCodeResult, PythonCodeTool
from tables.models.crew_models import (
    AgentConfiguredTools,
    AgentMcpTools,
    AgentPythonCodeTools,
    TaskMcpTools,
    TaskPythonCodeTools,
)
from tables.models.embedding_models import DefaultEmbeddingConfig
from tables.models.graph_models import (
    Condition,
    ConditionGroup,
    DecisionTableNode,
    EndNode,
    LLMNode,
    StartNode,
    Organization,
    OrganizationUser,
    GraphOrganization,
    GraphOrganizationUser,
)
from tables.models.llm_models import (
    DefaultLLMConfig,
    RealtimeModel,
    RealtimeConfig,
    RealtimeTranscriptionModel,
    RealtimeTranscriptionConfig,
)
from tables.models.realtime_models import (
    RealtimeSessionItem,
    RealtimeAgent,
    RealtimeAgentChat,
)
from tables.models.tag_models import AgentTag, CrewTag, GraphTag
from tables.models.vector_models import MemoryDatabase
from tables.validators.tool_config_validator import ToolConfigValidator, eval_any
from tables.models import (
    AgentSessionMessage,
    TaskSessionMessage,
    Session,
    UserSessionMessage,
)
from tables.models import (
    ToolConfig,
)

from django.core.exceptions import ValidationError
from tables.exceptions import InvalidTaskOrderError


class LLMConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = LLMConfig
        fields = "__all__"


class DefaultLLMConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = DefaultLLMConfig
        fields = "__all__"


class ProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Provider
        fields = "__all__"


class LLMModelSerializer(serializers.ModelSerializer):

    class Meta:
        model = LLMModel
        fields = "__all__"


class EmbeddingModelSerializer(serializers.ModelSerializer):

    class Meta:
        model = EmbeddingModel
        fields = "__all__"


class EmbeddingConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmbeddingConfig
        fields = "__all__"


class DefaultEmbeddingConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = DefaultEmbeddingConfig
        fields = [
            "model",
            "task_type",
            "api_key",
        ]


class ToolConfigFieldSerializer(serializers.ModelSerializer):

    class Meta:
        model = ToolConfigField
        fields = ["name", "description", "data_type", "required"]


class ToolSerializer(serializers.ModelSerializer):
    tool_fields = ToolConfigFieldSerializer(many=True, read_only=True)

    class Meta:
        model = Tool
        fields = ["id", "name", "name_alias", "description", "enabled", "tool_fields"]
        read_only_fields = [
            "id",
            "name",
            "name_alias",
            "description",
            "tool_fields",
        ]


class PythonCodeSerializer(serializers.ModelSerializer):
    libraries = serializers.ListField(
        child=serializers.CharField(),
        write_only=False,
        help_text="A list of library names.",
    )

    class Meta:
        model = PythonCode
        fields = "__all__"

    def to_representation(self, instance):
        """Convert 'libraries' string to a list of strings for output."""
        representation = super().to_representation(instance)
        representation["libraries"] = (
            list(filter(None, instance.libraries.split(" ")))
            if instance.libraries
            else []
        )
        return representation

    def to_internal_value(self, data):
        """Convert 'libraries' list of strings to a space-separated string for storage."""
        internal_value = super().to_internal_value(data)
        libraries = data.get("libraries", [])
        if isinstance(libraries, list):
            internal_value["libraries"] = " ".join(libraries)
        return internal_value


class PythonCodeToolSerializer(serializers.ModelSerializer):
    python_code = PythonCodeSerializer()
    built_in = serializers.ReadOnlyField()

    class Meta:
        model = PythonCodeTool
        fields = [
            "id",
            "name",
            "description",
            "args_schema",
            "python_code",
            "favorite",
            "built_in",
        ]

    def create(self, validated_data):
        python_code_data = validated_data.pop("python_code")
        python_code = PythonCode.objects.create(**python_code_data)
        python_code_tool = PythonCodeTool.objects.create(
            python_code=python_code, **validated_data
        )
        return python_code_tool

    def update(self, instance, validated_data):
        if instance.built_in:
            raise BuiltInToolModificationError()

        python_code_data = validated_data.pop("python_code", None)

        if python_code_data:
            python_code = instance.python_code
            for attr, value in python_code_data.items():
                setattr(python_code, attr, value)
            python_code.save()

        for attr, value in validated_data.items():
            if attr != "built_in":
                setattr(instance, attr, value)
        instance.save()

        return instance

    def partial_update(self, instance, validated_data):
        return self.update(instance, validated_data)


class McpToolSerializer(serializers.ModelSerializer):
    class Meta:
        model = McpTool
        fields = "__all__"


class RealtimeAgentSerializer(serializers.ModelSerializer):

    similarity_threshold = serializers.DecimalField(
        max_digits=3,
        decimal_places=2,
        min_value=Decimal("0.00"),
        max_value=Decimal("1.00"),
        required=False,
    )

    search_limit = serializers.IntegerField(min_value=1, max_value=1000, required=False)

    class Meta:
        model = RealtimeAgent
        exclude = ["agent"]


class AgentReadSerializer(serializers.ModelSerializer):
    tools = serializers.SerializerMethodField()
    realtime_agent = RealtimeAgentSerializer(read_only=True)
    similarity_threshold = serializers.DecimalField(
        max_digits=3,
        decimal_places=2,
        min_value=Decimal("0.00"),
        max_value=Decimal("1.00"),
        required=False,
    )

    class Meta:
        model = Agent
        fields = [
            "id",
            "role",
            "goal",
            "backstory",
            "tools",
            "max_iter",
            "max_rpm",
            "max_execution_time",
            "memory",
            "allow_delegation",
            "cache",
            "allow_code_execution",
            "max_retry_limit",
            "respect_context_window",
            "default_temperature",
            "llm_config",
            "fcm_llm_config",
            "knowledge_collection",
            "realtime_agent",
            "search_limit",
            "similarity_threshold",
        ]

    def get_tools(self, agent: Agent) -> list[dict]:
        tools = []

        python_tools = PythonCodeTool.objects.filter(
            id__in=AgentPythonCodeTools.objects.filter(agent_id=agent.id).values_list(
                "pythoncodetool_id", flat=True
            )
        )
        for tool in python_tools:
            tools.append(BaseToolSerializer(tool).data)

        configured_tools = ToolConfig.objects.filter(
            id__in=AgentConfiguredTools.objects.filter(agent_id=agent.id).values_list(
                "toolconfig_id", flat=True
            )
        )
        for tool in configured_tools:
            tools.append(BaseToolSerializer(tool).data)

        mcp_tools = McpTool.objects.filter(
            id__in=AgentMcpTools.objects.filter(agent_id=agent.id).values_list(
                "mcptool_id", flat=True
            )
        )
        for tool in mcp_tools:
            tools.append(BaseToolSerializer(tool).data)

        return tools


class AgentWriteSerializer(serializers.ModelSerializer):
    tool_ids = serializers.ListField(
        child=serializers.CharField(),
        # write_only=True,
        required=False,
    )
    realtime_agent = RealtimeAgentSerializer(required=False)
    llm_config = serializers.PrimaryKeyRelatedField(
        queryset=LLMConfig.objects.all(), required=False, allow_null=True
    )
    similarity_threshold = serializers.DecimalField(
        max_digits=3,
        decimal_places=2,
        min_value=Decimal("0.00"),
        max_value=Decimal("1.00"),
        required=False,
    )
    search_limit = serializers.IntegerField(min_value=1, max_value=1000, required=False)

    class Meta:
        model = Agent
        fields = [
            "id",
            "role",
            "goal",
            "backstory",
            "tool_ids",
            "max_iter",
            "max_rpm",
            "max_execution_time",
            "memory",
            "allow_delegation",
            "cache",
            "allow_code_execution",
            "max_retry_limit",
            "respect_context_window",
            "default_temperature",
            "llm_config",
            "fcm_llm_config",
            "knowledge_collection",
            "search_limit",
            "similarity_threshold",
            "realtime_agent",
        ]

    def _resolve_tool_ids(self, tool_ids: list[str]) -> dict[str, list[int]]:
        tools = {
            "configured-tool-list": [],
            "python-code-tool-list": [],
            "mcp-tool-list": [],
        }
        for tool_id in tool_ids:
            try:
                prefix, pk = tool_id.split(":")
                if prefix == "configured-tool":
                    tools["configured-tool-list"].append(pk)
                elif prefix == "python-code-tool":
                    tools["python-code-tool-list"].append(pk)
                elif prefix == "mcp-tool":
                    tools["mcp-tool-list"].append(pk)
                else:
                    raise ValueError(f"Unknown tool prefix: {prefix}")
            except Exception as e:
                raise serializers.ValidationError({"tool_ids": str(e)})

        return tools

    def create(self, validated_data: dict):
        tool_ids = validated_data.pop("tool_ids", [])
        tools = self._resolve_tool_ids(tool_ids)

        realtime_agent_data = validated_data.pop("realtime_agent", None)
        agent: Agent = super().create(validated_data)

        AgentConfiguredTools.objects.filter(agent_id=agent.id).delete()
        AgentConfiguredTools.objects.bulk_create(
            [
                AgentConfiguredTools(agent_id=agent.id, toolconfig_id=tool.id)
                for tool in ToolConfig.objects.filter(
                    id__in=tools.get("configured-tool-list", [])
                )
            ]
        )

        AgentPythonCodeTools.objects.filter(agent_id=agent.id).delete()
        AgentPythonCodeTools.objects.bulk_create(
            [
                AgentPythonCodeTools(agent_id=agent.id, pythoncodetool_id=tool.id)
                for tool in PythonCodeTool.objects.filter(
                    id__in=tools.get("python-code-tool-list", [])
                )
            ]
        )

        AgentMcpTools.objects.filter(agent_id=agent.id).delete()
        AgentMcpTools.objects.bulk_create(
            [
                AgentMcpTools(agent_id=agent.id, mcptool_id=tool.id)
                for tool in McpTool.objects.filter(
                    id__in=tools.get("mcp-tool-list", [])
                )
            ]
        )

        if realtime_agent_data:
            RealtimeAgent.objects.create(agent=agent, **realtime_agent_data)
        else:
            RealtimeAgent.objects.create(agent=agent)

        return agent

    def update(self, instance: Agent, validated_data: dict):
        tool_ids = validated_data.pop("tool_ids", [])
        tools = self._resolve_tool_ids(tool_ids)

        realtime_agent_data: dict | None = validated_data.pop("realtime_agent", None)
        instance = super().update(instance, validated_data)

        # configured_tools
        AgentConfiguredTools.objects.filter(agent_id=instance.id).delete()
        AgentConfiguredTools.objects.bulk_create(
            [
                AgentConfiguredTools(agent_id=instance.id, toolconfig_id=tool.id)
                for tool in ToolConfig.objects.filter(
                    id__in=tools.get("configured-tool-list", [])
                )
            ]
        )

        # python_code_tools
        AgentPythonCodeTools.objects.filter(agent_id=instance.id).delete()
        AgentPythonCodeTools.objects.bulk_create(
            [
                AgentPythonCodeTools(agent_id=instance.id, pythoncodetool_id=tool.id)
                for tool in PythonCodeTool.objects.filter(
                    id__in=tools.get("python-code-tool-list", [])
                )
            ]
        )

        # mcp_tools
        AgentMcpTools.objects.filter(agent_id=instance.id).delete()
        AgentMcpTools.objects.bulk_create(
            [
                AgentMcpTools(agent_id=instance.id, mcptool_id=tool.id)
                for tool in McpTool.objects.filter(
                    id__in=tools.get("mcp-tool-list", [])
                )
            ]
        )

        if realtime_agent_data:
            realtime_agent, _ = RealtimeAgent.objects.get_or_create(agent=instance)
            for attr, value in realtime_agent_data.items():
                setattr(realtime_agent, attr, value)
            realtime_agent.save()

        return instance


class TemplateAgentSerializer(serializers.ModelSerializer):
    configured_tools = serializers.PrimaryKeyRelatedField(
        many=True, queryset=ToolConfig.objects.all()
    )

    class Meta:
        model = TemplateAgent
        fields = "__all__"


class TaskContextListField(serializers.Field):
    """
    Custom field to handle task context list as integers.
    """

    def to_representation(self, value):
        """Convert TaskContext queryset to list of context task IDs"""
        if value is None:
            return []
        return [tc.context_id for tc in value.all()]

    def to_internal_value(self, data):
        """Convert list of integers to validated context task IDs"""
        if not isinstance(data, list):
            raise serializers.ValidationError("Expected a list of integers.")

        if not data:
            return []

        context_ids = []
        for item in data:
            if not isinstance(item, int):
                raise serializers.ValidationError("All items must be integers.")
            context_ids.append(item)

        return context_ids

    def validate_context_tasks(self, context_ids, task_instance=None, task_data=None):
        """Validate context task constraints"""
        if not context_ids:
            return context_ids

        task_order = None
        crew_id = None

        if task_instance:
            task_order = (
                task_data.get("order", task_instance.order)
                if task_data
                else task_instance.order
            )
            crew_id = (
                task_data.get("crew", task_instance.crew_id)
                if task_data
                else task_instance.crew_id
            )
        elif task_data:
            task_order = task_data.get("order")
            crew_id = task_data.get("crew")

        if task_order is None:
            raise serializers.ValidationError(
                "Task must have an order to assign context tasks."
            )

        if task_instance and task_instance.id in context_ids:
            raise serializers.ValidationError(
                "A task cannot be assigned as its own context."
            )

        # context tasks existing
        context_tasks = Task.objects.filter(id__in=context_ids)
        if context_tasks.count() != len(context_ids):
            existing_ids = set(context_tasks.values_list("id", flat=True))
            missing_ids = set(context_ids) - existing_ids
            raise serializers.ValidationError(
                f"Context tasks do not exist: {list(missing_ids)}"
            )

        # order constraint
        invalid_tasks = context_tasks.filter(order__gte=task_order)
        if invalid_tasks.exists():
            invalid_names = list(invalid_tasks.values_list("name", flat=True))
            raise serializers.ValidationError(
                f"Context tasks must have lower order. Invalid tasks: {invalid_names}"
            )

        # crew constraint
        if crew_id:
            different_crew_tasks = context_tasks.exclude(crew_id=crew_id)
            if different_crew_tasks.exists():
                raise serializers.ValidationError(
                    "Context tasks must belong to the same crew."
                )

        # self-reference constraint
        if task_instance and task_instance.id in context_ids:
            raise serializers.ValidationError("Task cannot be a context of itself.")

        return context_ids


class TaskReadSerializer(serializers.ModelSerializer):
    task_context_list = TaskContextListField(read_only=True)
    tools = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = "__all__"

    def get_tools(self, task: Task) -> list[dict]:
        all_task_tools = chain(
            task.task_configured_tool_list.all(),
            task.task_python_code_tool_list.all(),
            task.task_mcp_tool_list.all(),
        )
        return [BaseToolSerializer(task_tool.tool).data for task_tool in all_task_tools]


class TaskWriteSerializer(serializers.ModelSerializer):
    task_context_list = TaskContextListField(required=False)
    tool_ids = serializers.ListField(
        child=serializers.CharField(),
        # write_only=True,
        required=False,
    )

    class Meta:
        model = Task
        fields = "__all__"

    def validate(self, attrs):
        attrs = super().validate(attrs)

        task_order = attrs.get("order", self.instance.order if self.instance else None)

        if task_order is None:
            return attrs

        incoming_context_ids = self.initial_data.get("task_context_list", None)

        ids_to_validate = []

        if incoming_context_ids is not None:
            # Case A: A new context list was explicitly sent in the request.
            task_context_field = self.fields["task_context_list"]
            ids_to_validate = task_context_field.validate_context_tasks(
                incoming_context_ids, task_instance=self.instance, task_data=attrs
            )
        elif "order" in attrs and self.instance:
            # Case B: The 'order' is being changed, but no context list was sent.
            ids_to_validate = list(
                self.instance.task_context_list.values_list("context_id", flat=True)
            )

        if ids_to_validate:
            valid_context_count = Task.objects.filter(
                id__in=ids_to_validate, order__lt=task_order
            ).count()

            if valid_context_count < len(ids_to_validate):
                raise InvalidTaskOrderError

        if "order" in attrs and self.instance:
            dependent_tasks = Task.objects.filter(
                task_context_list__context=self.instance
            )

            if dependent_tasks.filter(order__lte=task_order).exists():
                raise InvalidTaskOrderError

        if incoming_context_ids is not None:
            attrs["_validated_context_ids"] = ids_to_validate

        return attrs

    def create(self, validated_data):
        context_ids = validated_data.pop("_validated_context_ids", [])
        validated_data.pop("task_context_list", None)

        tool_ids = validated_data.pop("tool_ids", None)

        task = super().create(validated_data)

        if tool_ids is not None:
            self._update_task_tools(task=task, tool_ids=tool_ids)

        if context_ids is not None:
            self._update_task_contexts(task, context_ids)

        return task

    def update(self, instance, validated_data):
        context_ids = validated_data.pop("_validated_context_ids", None)
        validated_data.pop("task_context_list", None)

        tool_ids = validated_data.pop("tool_ids", None)

        task = super().update(instance, validated_data)

        if tool_ids is not None:
            self._update_task_tools(task=task, tool_ids=tool_ids)

        if context_ids is not None:
            self._update_task_contexts(task, context_ids)

        return task  # TODO: responce

    def _update_task_tools(self, task: Task, tool_ids: list[str]):
        TaskPythonCodeTools.objects.filter(task=task).delete()
        TaskConfiguredTools.objects.filter(task=task).delete()
        TaskMcpTools.objects.filter(task=task).delete()

        python_code_tool_list = []
        configured_tool_list = []
        mcp_tool_list = []
        for tool_id in tool_ids:

            prefix, id_ = tool_id.split(":")
            if prefix == "python-code-tool":
                python_code_tool = PythonCodeTool.objects.get(pk=id_)
                instance = TaskPythonCodeTools(task=task, tool=python_code_tool)
                instance.full_clean()
                python_code_tool_list.append(instance)
            elif prefix == "configured-tool":
                configured_tool = ToolConfig.objects.get(pk=id_)
                instance = TaskConfiguredTools(task=task, tool=configured_tool)
                instance.full_clean()
                configured_tool_list.append(instance)
            elif prefix == "mcp-tool":
                mcp_tool = McpTool.objects.get(pk=id_)
                instance = TaskMcpTools(task=task, tool=mcp_tool)
                instance.full_clean()
                mcp_tool_list.append(instance)

        TaskPythonCodeTools.objects.bulk_create(python_code_tool_list)
        TaskConfiguredTools.objects.bulk_create(configured_tool_list)
        TaskMcpTools.objects.bulk_create(mcp_tool_list)

    def _update_task_contexts(self, task, context_ids):
        TaskContext.objects.filter(task=task).delete()
        context_objects = []

        for context_id in context_ids:
            context = Task.objects.get(id=context_id)
            instance = TaskContext(task=task, context=context)
            instance.full_clean()
            context_objects.append(instance)

        TaskContext.objects.bulk_create(context_objects)


class CrewSerializer(serializers.ModelSerializer):
    tasks = serializers.PrimaryKeyRelatedField(
        many=True, read_only=True, source="task_set"
    )
    manager_llm_config = serializers.PrimaryKeyRelatedField(
        queryset=LLMConfig.objects.all(),
        required=False,
        allow_null=True,
    )
    embedding_config = serializers.PrimaryKeyRelatedField(
        queryset=EmbeddingConfig.objects.all(),
        required=False,
        allow_null=True,
    )
    memory_llm_config = serializers.PrimaryKeyRelatedField(
        queryset=LLMConfig.objects.all(),
        required=False,
        allow_null=True,
    )
    agents = serializers.PrimaryKeyRelatedField(
        queryset=Agent.objects.all(),
        many=True,
        required=False,
        allow_null=True,
    )
    similarity_threshold = serializers.DecimalField(
        max_digits=3,
        decimal_places=2,
        min_value=Decimal("0.00"),
        max_value=Decimal("1.00"),
        required=False,
    )
    search_limit = serializers.IntegerField(min_value=1, max_value=1000, required=False)

    class Meta:
        model = Crew
        fields = "__all__"

    # def validate(self, data):
    #     default_config = DefaultCrewConfig.load()
    #     # TODO: what is happening
    #     default_fields = ["manager_llm_config", "process", "memory", "embedding_config"]

    #     for field in default_fields:
    #         if data.get(field) is None:
    #             data[field] = getattr(default_config, field)

    #     return data


class ToolConfigSerializer(serializers.ModelSerializer):

    def __init__(
        self, *args, tool_config_validator: ToolConfigValidator | None = None, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.tool_config_validator = tool_config_validator or ToolConfigValidator(
            validate_null_fields=False, validate_missing_reqired_fields=False
        )

    class Meta:
        model = ToolConfig
        fields = "__all__"

    def validate(self, data: dict):

        name: str = data.get("name")
        tool: Tool = data.get("tool")
        configuration: dict = data.get("configuration", dict())

        if name is None:
            raise ToolConfigSerializerError("Name for configuration is not provided.")
        if tool is None:
            raise ToolConfigSerializerError("Tool is not provided.")
        if configuration is None:
            raise ToolConfigSerializerError("Configuration is not provided.")
        try:
            self.tool_config_validator.validate(
                name=name,
                tool=tool,
                configuration=configuration,
            )
        except ValidationError as e:
            raise ToolConfigSerializerError(e.message)

        return data

    # TODO: get rid of format parameter. Should use one as  pydantic.
    # using in: convert_configured_tool_to_pydantic()
    def to_representation(
        self, instance: ToolConfig, format: Literal["rest", "pydantic"] = "rest"
    ) -> dict:

        data = super().to_representation(instance)
        configuration: dict = data["configuration"]

        for key, value in configuration.items():
            tool_config_field: ToolConfigField = instance.get_tool_config_field(key)
            if tool_config_field.data_type == ToolConfigField.FieldType.ANY:

                # Get rid of ternar operator. Use only value["decoded_value"] (as pydantic)
                value = (
                    value["user_input"] if format == "rest" else value["decoded_value"]
                )

                configuration[key] = value

        data["is_completed"] = self.tool_config_validator.validate_is_completed(
            instance.tool, configuration
        )
        return data

    def to_internal_value(self, data: dict) -> dict:

        try:
            tool: Tool = Tool.objects.get(pk=data.get("tool"))
        except Tool.DoesNotExist:
            raise ToolConfigSerializerError(
                f"Tool with id: '{data.get("tool")}' does not exist", status_code=404
            )
        configuration: dict = data.get("configuration", dict())

        tool_config_fields = tool.get_tool_config_fields()

        for key, value in configuration.items():
            if key not in tool_config_fields:
                raise ToolConfigSerializerError(
                    f"Tool with id: '{tool.pk}' does not support field '{key}'. Available configuration fields: {[field for field in tool_config_fields.keys()]}",
                    status_code=404,
                )
            field = tool_config_fields.get(key)
            if field.data_type == ToolConfigField.FieldType.ANY:
                decoded_value = eval_any(key, value)

                # Problem with storring multivalued field in DB.
                # Potential solution: get rid of "user_input" and
                # dynamicaly calculate it from "decoded_value" if needed
                configuration[key] = {
                    "user_input": value,
                    "decoded_value": decoded_value,
                }

        data["configuration"] = configuration

        tool_config = super().to_internal_value(data)

        return tool_config


class UserSessionMessageSerializer(serializers.ModelSerializer):

    class Meta:
        model = UserSessionMessage

        fields = "__all__"


class TaskSessionMessageSerializer(serializers.ModelSerializer):

    class Meta:
        model = TaskSessionMessage

        fields = "__all__"


class AgentSessionMessageSerializer(serializers.ModelSerializer):

    class Meta:
        model = AgentSessionMessage
        fields = "__all__"


class PythonCodeResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = PythonCodeResult
        fields = "__all__"


class CrewNodeSerializer(serializers.ModelSerializer):
    crew = CrewSerializer(read_only=True)
    crew_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = CrewNode
        fields = "__all__"
        read_only_fields = ["crew"]

    def validate_crew_id(self, value):
        if not Crew.objects.only("id").filter(id=value).exists():
            raise serializers.ValidationError("Invalid crew_id: crew does not exist.")
        return value

    def update(self, instance, validated_data):
        if "crew_id" in validated_data:
            instance.crew_id = validated_data["crew_id"]
        return super().update(instance, validated_data)


class PythonNodeSerializer(serializers.ModelSerializer):
    python_code = PythonCodeSerializer()

    class Meta:
        model = PythonNode
        fields = "__all__"

    def create(self, validated_data):
        python_code_data = validated_data.pop("python_code")
        python_code = PythonCode.objects.create(**python_code_data)
        pytohn_node = PythonNode.objects.create(
            python_code=python_code, **validated_data
        )
        return pytohn_node

    def update(self, instance, validated_data):
        python_code_data = validated_data.pop("python_code", None)

        # Update nested PythonCode instance if provided
        if python_code_data:
            python_code = instance.python_code
            for attr, value in python_code_data.items():
                setattr(python_code, attr, value)
            python_code.save()

        # Update PythonNode fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        return instance

    def partial_update(self, instance, validated_data):
        # Delegate to the update method for consistency
        return self.update(instance, validated_data)


class FileExtractorNodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = FileExtractorNode
        fields = "__all__"


class AudioTranscriptionNodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AudioTranscriptionNode
        fields = "__all__"


class LLMNodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LLMNode
        fields = "__all__"


class EdgeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Edge
        fields = "__all__"


class SubGraphNodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubGraphNode
        fields = "__all__"

    def validate(self, attrs):
        graph = attrs.get("graph") or getattr(self.instance, "graph", None)
        subgraph = attrs.get("subgraph") or getattr(self.instance, "subgraph", None)

        if graph and subgraph and graph == subgraph:
            raise serializers.ValidationError("Graph and subgraph cannot be the same.")

        return attrs


class ConditionalEdgeSerializer(serializers.ModelSerializer):
    python_code = PythonCodeSerializer()

    class Meta:
        model = ConditionalEdge
        fields = "__all__"

    def create(self, validated_data):
        python_code_data = validated_data.pop("python_code")
        python_code = PythonCode.objects.create(**python_code_data)
        conditional_edge = ConditionalEdge.objects.create(
            python_code=python_code, **validated_data
        )
        return conditional_edge

    def update(self, instance, validated_data):
        python_code_data = validated_data.pop("python_code", None)

        # Update nested PythonCode instance if provided
        if python_code_data:
            python_code = instance.python_code
            for attr, value in python_code_data.items():
                setattr(python_code, attr, value)
            python_code.save()

        # Update PythonNode fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        return instance

    def partial_update(self, instance, validated_data):
        # Delegate to the update method for consistency
        return self.update(instance, validated_data)


class StartNodeSerializer(serializers.ModelSerializer):
    node_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = StartNode
        fields = ["id", "graph", "variables", "node_name"]
        read_only_fields = ["node_name"]

    def get_node_name(self, obj):
        return "__start__"


class EndNodeSerializer(serializers.ModelSerializer):
    node_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = EndNode
        fields = ["id", "graph", "output_map", "node_name"]
        read_only_fields = ["node_name"]

    def get_node_name(self, obj):
        return "__end_node__"


class SessionSerializer(serializers.ModelSerializer):

    class Meta:
        model = Session
        fields = "__all__"
        read_only_fields = [
            "id",
            "status",
            "status_updated_at",
            "variables",
            "created_at",
            "finished_at",
            "graph",
            "graph_schema",
        ]


class SessionLightSerializer(serializers.ModelSerializer):
    class Meta:
        model = Session
        fields = (
            "id",
            "graph_id",
            "status",
            "status_updated_at",
            "created_at",
            "finished_at",
        )


class GraphSessionMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = GraphSessionMessage
        fields = "__all__"


class MemorySerializer(serializers.ModelSerializer):
    class Meta:
        model = MemoryDatabase
        fields = ["id", "payload"]


class CrewTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = CrewTag
        fields = "__all__"


class AgentTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentTag
        fields = "__all__"


class GraphTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = GraphTag
        fields = "__all__"


class GraphLightSerializer(serializers.ModelSerializer):
    tags = GraphTagSerializer(many=True, read_only=True)

    class Meta:
        model = Graph
        fields = [
            "id",
            "name",
            "description",
            "tags",
        ]


class RealtimeModelSerializer(serializers.ModelSerializer):

    class Meta:
        model = RealtimeModel
        fields = "__all__"


class RealtimeConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = RealtimeConfig
        fields = "__all__"


class RealtimeTranscriptionModelSerializer(serializers.ModelSerializer):

    class Meta:
        model = RealtimeTranscriptionModel
        fields = "__all__"


class RealtimeTranscriptionConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = RealtimeTranscriptionConfig
        fields = "__all__"


class RealtimeSessionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = RealtimeSessionItem
        fields = "__all__"


class RealtimeAgentChatSerializer(serializers.ModelSerializer):
    class Meta:
        model = RealtimeAgentChat
        fields = "__all__"


class ConditionSerializer(serializers.ModelSerializer):
    condition_group = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Condition
        fields = "__all__"


class ConditionGroupSerializer(serializers.ModelSerializer):
    conditions = ConditionSerializer(many=True, required=False)
    decision_table_node = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = ConditionGroup
        fields = "__all__"


class DecisionTableNodeSerializer(serializers.ModelSerializer):
    condition_groups = ConditionGroupSerializer(many=True, required=False)

    class Meta:
        model = DecisionTableNode
        fields = "__all__"


class WebhookTriggerNodeSerializer(serializers.ModelSerializer):
    python_code = PythonCodeSerializer()
    webhook_trigger_path = serializers.CharField(required=False, allow_blank=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["webhook_trigger_path"] = (
            instance.webhook_trigger.path if instance.webhook_trigger else None
        )
        return data

    class Meta:
        model = WebhookTriggerNode
        exclude = ["webhook_trigger"]

    def create(self, validated_data):
        python_code_data = validated_data.pop("python_code")
        python_code = PythonCode.objects.create(**python_code_data)

        webhook_trigger_path = validated_data.pop("webhook_trigger_path", "").strip()
        if not webhook_trigger_path:
            webhook_trigger_path = "default"

        webhook_trigger, _ = WebhookTrigger.objects.get_or_create(
            path=webhook_trigger_path
        )

        webhook_trigger_node = WebhookTriggerNode.objects.create(
            python_code=python_code,
            webhook_trigger=webhook_trigger,
            **validated_data,
        )
        return webhook_trigger_node

    def update(self, instance, validated_data):
        python_code_data = validated_data.pop("python_code", None)
        if python_code_data:
            python_code = instance.python_code
            for attr, value in python_code_data.items():
                setattr(python_code, attr, value)
            python_code.save()

        webhook_trigger_path = validated_data.pop("webhook_trigger_path", None)
        if webhook_trigger_path is not None:
            webhook_trigger_path = webhook_trigger_path.strip() or "default"
            webhook_trigger, _ = WebhookTrigger.objects.get_or_create(
                path=webhook_trigger_path
            )
            instance.webhook_trigger = webhook_trigger

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance

    def partial_update(self, instance, validated_data):
        return self.update(instance, validated_data)


class WebhookTriggerSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookTrigger
        fields = "__all__"


class GraphSerializer(serializers.ModelSerializer):
    # Reverse relationships
    crew_node_list = CrewNodeSerializer(many=True, read_only=True)
    python_node_list = PythonNodeSerializer(many=True, read_only=True)
    file_extractor_node_list = FileExtractorNodeSerializer(many=True, read_only=True)
    audio_transcription_node_list = AudioTranscriptionNodeSerializer(
        many=True, read_only=True
    )
    edge_list = EdgeSerializer(many=True, read_only=True)
    conditional_edge_list = ConditionalEdgeSerializer(many=True, read_only=True)
    llm_node_list = LLMNodeSerializer(many=True, read_only=True)
    webhook_trigger_node_list = WebhookTriggerNodeSerializer(many=True, read_only=True)
    start_node_list = StartNodeSerializer(many=True, read_only=True)
    decision_table_node_list = DecisionTableNodeSerializer(many=True, read_only=True)
    subgraph_node_list = SubGraphNodeSerializer(many=True, read_only=True)
    end_node_list = EndNodeSerializer(many=True, read_only=True, source="end_node")

    class Meta:
        model = Graph
        fields = [
            "id",
            "name",
            "metadata",
            "description",
            "crew_node_list",
            "python_node_list",
            "file_extractor_node_list",
            "audio_transcription_node_list",
            "edge_list",
            "conditional_edge_list",
            "llm_node_list",
            "webhook_trigger_node_list",
            "decision_table_node_list",
            "subgraph_node_list",
            "start_node_list",
            "end_node_list",
            "time_to_live",
            "persistent_variables",
        ]


class GraphFileReadSerializer(serializers.ModelSerializer):

    file = serializers.FileField(use_url=True)

    class Meta:
        model = GraphFile
        fields = [
            "id",
            "graph",
            "domain_key",
            "name",
            "content_type",
            "size",
            "file",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class OrganizationSerializer(serializers.ModelSerializer):

    class Meta:
        model = Organization
        fields = ["id", "name"]


class OrganizationUserSerializer(serializers.ModelSerializer):

    class Meta:
        model = OrganizationUser
        fields = ["id", "organization", "name"]


class GraphOrganizationSerializer(serializers.ModelSerializer):

    class Meta:
        model = GraphOrganization
        fields = [
            "id",
            "graph",
            "organization",
            "persistent_variables",
            "user_variables",
        ]

    def validate(self, attrs):
        graph = attrs.get("graph") or getattr(self.instance, "graph", None)
        if not graph:
            raise serializers.ValidationError("Graph is required to validate variables")

        organization_variables = attrs.get("persistent_variables", {})
        user_variables = attrs.get("user_variables", {})

        qs = GraphOrganization.objects.filter(graph=graph)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise serializers.ValidationError("This flow already has an organization")

        start_node: StartNode = graph.start_node_list.first()
        for key in user_variables:
            if key not in start_node.variables:
                raise serializers.ValidationError(
                    {
                        "user_variables": f"Provided user_variables have to be in flow domain. Variable `{key}` is not in domain."
                    }
                )
        for key in organization_variables:
            if key not in start_node.variables:
                raise serializers.ValidationError(
                    {
                        "persistent_variables": f"Provided persistent_variables have to be in flow domain. Variable `{key}` is not in domain."
                    }
                )
            if key in user_variables:
                raise serializers.ValidationError(
                    {
                        "user_variables": f"User variables and Organization variables cannot have same values. Issue with key `{key}`"
                    }
                )

        return super().validate(attrs)


class GraphOrganizationUserSerializer(serializers.ModelSerializer):

    class Meta:
        model = GraphOrganizationUser
        fields = ["id", "graph", "user", "persistent_variables"]
        read_only_fields = ["id", "persistent_variables"]


class ChunkSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chunk
        fields = "__all__"

    def validate_document_id(self, value):
        if not DocumentMetadata.objects.filter(document_id=value).exists():
            raise serializers.ValidationError("Document with this id does not exist.")
        return value