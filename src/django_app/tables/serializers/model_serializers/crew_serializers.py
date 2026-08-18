from itertools import chain
from typing import Literal

from rest_framework import serializers
from django.db.models import Model, Prefetch

from tables.models.mcp_models import McpTool
from tables.exceptions import (
    InvalidTaskOrderError,
    ToolConfigSerializerError,
)
from tables.models.crew_models import (
    Agent,
    AgentConfiguredTools,
    AgentMcpTools,
    AgentPythonCodeToolConfigs,
    AgentPythonCodeTools,
    Crew,
    Task,
    TaskConfiguredTools,
    TaskContext,
    TaskMcpTools,
    TaskPythonCodeToolConfigs,
    TaskPythonCodeTools,
    TemplateAgent,
    Tool,
    ToolConfig,
    ToolConfigField,
)
from tables.models.embedding_models import EmbeddingConfig
from tables.models.llm_models import LLMConfig
from tables.models.python_models import PythonCodeTool, PythonCodeToolConfig
from tables.models.realtime_models import RealtimeAgent
from tables.models import SourceCollection
from tables.models.knowledge_models import NaiveRag, GraphRag
from tables.serializers.org_scoped_fields import (
    OrgScopedPrimaryKeyRelatedField,
    resolve_active_org_id,
)
from tables.serializers.knowledge_serializers import (
    NestedSearchConfigSerializer,
    RagInputSerializer,
)
from tables.serializers.model_serializers.realtime_serializers import (
    RealtimeAgentReadSerializer,
    RealtimeAgentWriteSerializer,
)
from tables.serializers.serializers import BaseToolSerializer
from tables.services.rag_assignment_service import (
    RagAssignmentService,
    SearchConfigService,
)
from tables.validators.tool_config_validator import (
    ToolConfigValidator,
    eval_any,
)
from tables.serializers.utils.mixins import ToolsConnectionMixin


class ToolConfigFieldSerializer(serializers.ModelSerializer):
    class Meta:
        model = ToolConfigField
        fields = ["name", "description", "data_type", "required"]


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
        except serializers.ValidationError as e:
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
                f"Tool with id: '{data.get('tool')}' does not exist", status_code=404
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


class AgentReadSerializer(serializers.ModelSerializer):
    """
    DEPRECATED: AgentReadSerializer is deprecated. Use agents.AgentDefinition
    serializers + AgentNode instead. Exists only for backward compatibility
    with existing Agent rows.
    """

    tools = serializers.SerializerMethodField()
    realtime_agent = RealtimeAgentReadSerializer(read_only=True)
    rag = serializers.SerializerMethodField()
    search_configs = serializers.SerializerMethodField()

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
            "rag",
            "search_configs",
        ]

    def get_tools(self, agent: Agent) -> list[dict]:
        tools = []

        # Use prefetched data when available (from AgentViewSet queryset),
        # fall back to direct queries for non-prefetched contexts (e.g. create/update responses).
        if hasattr(agent, "prefetched_python_code_tools"):
            for link in agent.prefetched_python_code_tools:
                tools.append(BaseToolSerializer(link.pythoncodetool).data)
        else:
            for tool in PythonCodeTool.objects.filter(
                id__in=AgentPythonCodeTools.objects.filter(
                    agent_id=agent.id
                ).values_list("pythoncodetool_id", flat=True)
            ).select_related("python_code"):
                tools.append(BaseToolSerializer(tool).data)

        if hasattr(agent, "prefetched_python_code_tool_configs"):
            for link in agent.prefetched_python_code_tool_configs:
                tools.append(BaseToolSerializer(link.pythoncodetoolconfig).data)
        else:
            for tool in PythonCodeToolConfig.objects.filter(
                id__in=AgentPythonCodeToolConfigs.objects.filter(
                    agent_id=agent.id
                ).values_list("pythoncodetoolconfig_id", flat=True)
            ).select_related("tool__python_code"):
                tools.append(BaseToolSerializer(tool).data)

        if hasattr(agent, "prefetched_configured_tools"):
            for link in agent.prefetched_configured_tools:
                tools.append(BaseToolSerializer(link.toolconfig).data)
        else:
            for tool in (
                ToolConfig.objects.filter(
                    id__in=AgentConfiguredTools.objects.filter(
                        agent_id=agent.id
                    ).values_list("toolconfig_id", flat=True)
                )
                .select_related("tool")
                .prefetch_related(
                    Prefetch(
                        "tool__tool_fields",
                        queryset=ToolConfigField.objects.all(),
                        to_attr="prefetched_config_fields",
                    )
                )
            ):
                tools.append(BaseToolSerializer(tool).data)

        if hasattr(agent, "prefetched_mcp_tools"):
            for link in agent.prefetched_mcp_tools:
                tools.append(BaseToolSerializer(link.mcptool).data)
        else:
            for tool in McpTool.objects.filter(
                id__in=AgentMcpTools.objects.filter(agent_id=agent.id).values_list(
                    "mcptool_id", flat=True
                )
            ):
                tools.append(BaseToolSerializer(tool).data)

        return tools

    def get_rag(self, agent: Agent) -> dict | None:
        return RagAssignmentService.get_assigned_rag_info(agent)

    def get_search_configs(self, agent: Agent) -> dict | None:
        """
        Get all RAG search configurations in unified nested format
        Delegates to SearchConfigService for business logic
        """
        return SearchConfigService.get_search_configs(agent)


class AgentWriteSerializer(ToolsConnectionMixin, serializers.ModelSerializer):
    """
    DEPRECATED: AgentWriteSerializer is deprecated. Use agents.AgentDefinition
    serializers + AgentNode instead. Exists only for backward compatibility
    with existing Agent rows.
    """

    tool_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
    )
    realtime_agent = RealtimeAgentWriteSerializer(required=False)
    llm_config = OrgScopedPrimaryKeyRelatedField(
        queryset=LLMConfig.objects.all(), required=False, allow_null=True
    )
    fcm_llm_config = OrgScopedPrimaryKeyRelatedField(
        queryset=LLMConfig.objects.all(), required=False, allow_null=True
    )
    knowledge_collection = OrgScopedPrimaryKeyRelatedField(
        queryset=SourceCollection.objects.all(), required=False, allow_null=True
    )
    rag = RagInputSerializer(required=False, allow_null=True)
    search_configs = NestedSearchConfigSerializer(required=False, allow_null=True)

    # ORM path from a rag (naive/graph) up to its owning collection's org.
    _RAG_ORG_PATH = "base_rag_type__source_collection__org_id"
    _RAG_MODELS = {"naive": NaiveRag, "graph": GraphRag}

    def _assert_rag_in_active_org(self, rag_data):
        """A rag may only be assigned if it belongs to the active org (via its
        collection). Rejected like a non-existent pk — no existence leak."""
        request = self.context.get("request")
        if request is None or not rag_data:
            return
        model = self._RAG_MODELS.get(rag_data["rag_type"])
        org_id = resolve_active_org_id(request)
        in_org = (
            model is not None
            and model.objects.filter(
                pk=rag_data["rag_id"], **{self._RAG_ORG_PATH: org_id}
            ).exists()
        )
        if not in_org:
            raise serializers.ValidationError(
                {
                    "rag": f'Invalid pk "{rag_data.get("rag_id")}" - object does not exist.'
                }
            )

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
            "realtime_agent",
            "rag",
            "search_configs",
        ]

    def _get_tools_models_map(self) -> dict[type[Model], tuple[type[Model], str, str]]:
        return {
            ToolConfig: (AgentConfiguredTools, "configured-tool", "toolconfig_id"),
            PythonCodeTool: (
                AgentPythonCodeTools,
                "python-code-tool",
                "pythoncodetool_id",
            ),
            PythonCodeToolConfig: (
                AgentPythonCodeToolConfigs,
                "python-code-tool-config",
                "pythoncodetoolconfig_id",
            ),
            McpTool: (AgentMcpTools, "mcp-tool", "mcptool_id"),
        }

    def create(self, validated_data: dict):
        tool_ids = validated_data.pop("tool_ids", [])

        realtime_agent_data = validated_data.pop("realtime_agent", None)
        rag_data = validated_data.pop("rag", None)
        search_configs_data = validated_data.pop("search_configs", None)

        # Business Rule: If knowledge_collection provided, rag is REQUIRED
        knowledge_collection = validated_data.get("knowledge_collection")
        if knowledge_collection and not rag_data:
            raise serializers.ValidationError(
                {"rag": "This field is required when knowledge_collection is provided"}
            )

        self._assert_rag_in_active_org(rag_data)

        agent: Agent = super().create(validated_data)

        self._sync_tools(agent, "agent_id", tool_ids)

        # Handle RAG assignment
        if rag_data:
            RagAssignmentService.assign_rag_to_agent(
                agent=agent,
                rag_type=rag_data["rag_type"],
                rag_id=rag_data["rag_id"],
            )

        # Handle search configs
        if search_configs_data:
            SearchConfigService.apply_search_configs(agent, search_configs_data)
        elif rag_data:
            # RAG assigned but no config provided - create defaults
            if rag_data["rag_type"] == "naive":
                SearchConfigService.create_default_search_config(agent)
            elif rag_data["rag_type"] == "graph":
                SearchConfigService.create_default_graph_search_configs(agent)

        # Handle realtime agent
        if realtime_agent_data:
            RealtimeAgent.objects.create(agent=agent, **realtime_agent_data)
        else:
            RealtimeAgent.objects.create(agent=agent)

        return agent

    def update(self, instance: Agent, validated_data: dict):
        tool_ids = validated_data.pop("tool_ids", [])

        realtime_agent_data: dict | None = validated_data.pop("realtime_agent", None)
        rag_data = validated_data.pop("rag", None)
        search_configs_data = validated_data.pop("search_configs", None)

        # rags
        old_knowledge_collection = instance.knowledge_collection
        if "knowledge_collection" in validated_data:
            new_knowledge_collection = validated_data.get("knowledge_collection")

            if old_knowledge_collection != new_knowledge_collection:
                RagAssignmentService.unassign_all_rags_from_agent(instance)

                # If new collection is not None, require rag
                if new_knowledge_collection and not rag_data:
                    raise serializers.ValidationError(
                        {
                            "rag": "This field is required when changing to a new knowledge_collection"
                        }
                    )

        self._assert_rag_in_active_org(rag_data)

        instance = super().update(instance, validated_data)

        self._sync_tools(instance, "agent_id", tool_ids)

        # Handle RAG assignment
        if rag_data:
            RagAssignmentService.unassign_all_rags_from_agent(instance)
            RagAssignmentService.assign_rag_to_agent(
                agent=instance,
                rag_type=rag_data["rag_type"],
                rag_id=rag_data["rag_id"],
            )

        # Handle search configs (independent from RAG assignment)
        if search_configs_data:
            SearchConfigService.apply_search_configs(instance, search_configs_data)

        # Handle realtime agent
        if realtime_agent_data:
            realtime_agent, _ = RealtimeAgent.objects.get_or_create(agent=instance)
            for attr, value in realtime_agent_data.items():
                setattr(realtime_agent, attr, value)
            realtime_agent.save()

        return instance


class TaskContextListField(serializers.Field):
    """
    DEPRECATED: TaskContextListField is deprecated. Use AgentNodeTask.context_tasks
    instead. Exists only for backward compatibility with existing Task rows.

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
        context_tasks = Task.objects.filter(id__in=context_ids, crew_id=crew_id)
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

        return context_ids


class TaskReadSerializer(serializers.ModelSerializer):
    """
    DEPRECATED: TaskReadSerializer is deprecated. Use TaskNode/AgentNodeTask
    serializers instead. Exists only for backward compatibility with existing
    Task rows.
    """

    task_context_list = TaskContextListField(read_only=True)
    tools = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = "__all__"

    def get_tools(self, task: Task) -> list[dict]:
        all_task_tools = chain(
            task.task_configured_tool_list.all(),
            task.task_python_code_tool_list.all(),
            task.task_python_code_tool_config_list.all(),
            task.task_mcp_tool_list.all(),
        )
        return [BaseToolSerializer(task_tool.tool).data for task_tool in all_task_tools]


class TaskWriteSerializer(ToolsConnectionMixin, serializers.ModelSerializer):
    """
    DEPRECATED: TaskWriteSerializer is deprecated. Use TaskNode/AgentNodeTask
    serializers instead. Exists only for backward compatibility with existing
    Task rows.
    """

    task_context_list = TaskContextListField(required=False)
    tool_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
    )
    # Org isolation: a task may only reference an agent/crew from the caller's
    # active org (covers both create and update).
    agent = OrgScopedPrimaryKeyRelatedField(
        queryset=Agent.objects.all(), required=False, allow_null=True
    )
    crew = OrgScopedPrimaryKeyRelatedField(
        queryset=Crew.objects.all(), required=False, allow_null=True
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
            self._sync_tools(task, "task_id", tool_ids)

        if context_ids is not None:
            self._update_task_contexts(task, context_ids)

        return task

    def update(self, instance, validated_data):
        context_ids = validated_data.pop("_validated_context_ids", None)
        validated_data.pop("task_context_list", None)

        tool_ids = validated_data.pop("tool_ids", None)

        task = super().update(instance, validated_data)

        if tool_ids is not None:
            self._sync_tools(task, "task_id", tool_ids)

        if context_ids is not None:
            self._update_task_contexts(task, context_ids)

        return task

    def _get_tools_models_map(self) -> dict[type[Model], tuple[type[Model], str, str]]:
        return {
            ToolConfig: (TaskConfiguredTools, "configured-tool", "tool_id"),
            PythonCodeTool: (TaskPythonCodeTools, "python-code-tool", "tool_id"),
            PythonCodeToolConfig: (
                TaskPythonCodeToolConfigs,
                "python-code-tool-config",
                "tool_id",
            ),
            McpTool: (TaskMcpTools, "mcp-tool", "tool_id"),
        }

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
    """
    DEPRECATED: CrewSerializer is deprecated. Use the new Agent/Task graph node
    serializers (AgentNode, TaskNode) instead. Exists only for backward
    compatibility with existing Crew rows.
    """

    tasks = serializers.PrimaryKeyRelatedField(
        many=True, read_only=True, source="task_set"
    )
    manager_llm_config = OrgScopedPrimaryKeyRelatedField(
        queryset=LLMConfig.objects.all(),
        required=False,
        allow_null=True,
    )
    embedding_config = OrgScopedPrimaryKeyRelatedField(
        queryset=EmbeddingConfig.objects.all(),
        required=False,
        allow_null=True,
    )
    memory_llm_config = OrgScopedPrimaryKeyRelatedField(
        queryset=LLMConfig.objects.all(),
        required=False,
        allow_null=True,
    )
    planning_llm_config = OrgScopedPrimaryKeyRelatedField(
        queryset=LLMConfig.objects.all(),
        required=False,
        allow_null=True,
    )
    # Org isolation: only agents from the caller's active org are assignable.
    agents = OrgScopedPrimaryKeyRelatedField(
        queryset=Agent.objects.all(),
        many=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Crew
        fields = "__all__"
        read_only_fields = ["org", "created_by"]
