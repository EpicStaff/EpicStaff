from django.db.models import Q, Value, JSONField
from rest_framework import serializers

from tables.models.mcp_models import McpTool
from tables.models import (
    Agent,
    LLMConfig,
    LLMModel,
    PythonCode,
    PythonCodeTool,
    ToolConfig,
    RealtimeAgent,
    Crew,
    Task,
    Tool,
    EmbeddingConfig,
    EmbeddingModel,
    Graph,
    RealtimeConfig,
    RealtimeModel,
    RealtimeTranscriptionConfig,
    RealtimeTranscriptionModel,
    CrewNode,
)
from tables.serializers.model_serializers import (
    PythonNodeSerializer,
    EdgeSerializer,
    ConditionalEdgeSerializer,
    StartNodeSerializer,
    FileExtractorNodeSerializer,
    EndNodeSerializer,
    LLMNodeSerializer,
    DecisionTableNodeSerializer,
)
from tables.serializers.export_serializers import NestedCrewExportSerializer
from tables.utils.helpers import generate_new_unique_name
from tables.services.import_services import (
    ToolsImportService,
    AgentsImportService,
    CrewsImportService,
    LLMConfigsImportService,
    RealtimeConfigsImportService,
    RealtimeTranscriptionConfigsImportService,
    RealtimeAgentImportService,
    TasksImportService,
)


class FileImportSerializer(serializers.Serializer):

    file = serializers.FileField()


class PythonCodeImportSerializer(serializers.ModelSerializer):

    libraries = serializers.CharField(required=False, allow_blank=True, default="")

    class Meta:
        model = PythonCode
        exclude = ["id"]


class PythonCodeToolImportSerializer(serializers.ModelSerializer):

    python_code = PythonCodeImportSerializer()

    class Meta:
        model = PythonCodeTool
        exclude = ["favorite"]
        extra_kwargs = {
            "name": {"validators": []},
            "id": {"required": False, "read_only": False, "validators": []},
        }

    def create(self, validated_data):
        validated_data.pop("id", None)
        name = validated_data.pop("name")

        if PythonCodeTool.objects.filter(name=name).exists():
            existing_names = PythonCodeTool.objects.values_list("name", flat=True)
            name = generate_new_unique_name(name, existing_names)

        python_code_data = validated_data.pop("python_code", None)
        python_code = PythonCode.objects.create(**python_code_data)
        python_code_tool = PythonCodeTool.objects.create(
            name=name, python_code=python_code, **validated_data
        )
        return python_code_tool


class ToolConfigImportSerilizer(serializers.ModelSerializer):

    tool = serializers.CharField()

    class Meta:
        model = ToolConfig
        fields = "__all__"
        extra_kwargs = {
            "name": {"validators": []},
            "id": {"required": False, "read_only": False, "validators": []},
        }

    def create(self, validated_data):
        validated_data.pop("id", None)

        tool_name = validated_data.pop("name")
        configuration = validated_data.get("configuration")
        config = ToolConfig.objects.filter(
            tool__name=tool_name, configuration=configuration
        ).first()
        if config:
            return config

        new_tool_name = tool_name
        existing_names = ToolConfig.objects.values_list("name", flat=True)
        if existing_names:
            new_tool_name = generate_new_unique_name(tool_name, existing_names)

        alias = validated_data.pop("tool")
        tool = Tool.objects.get(name_alias=alias)
        config = ToolConfig.objects.create(
            tool=tool, name=new_tool_name, **validated_data
        )
        return config


class McpToolImportSerializer(serializers.ModelSerializer):

    class Meta:
        model = McpTool
        fields = "__all__"
        extra_kwargs = {
            "name": {"validators": []},
            "id": {"required": False, "read_only": False, "validators": []},
        }

    def create(self, validated_data: dict):
        validated_data.pop("id", None)
        full_match = McpTool.objects.filter(**validated_data).first()
        if full_match is not None:
            return full_match

        name = validated_data.pop("name")
        if McpTool.objects.filter(name=name).exists():
            existing_names = McpTool.objects.values_list("name", flat=True)
            name = generate_new_unique_name(name, existing_names)

        mcp_tool = McpTool.objects.create(name=name, **validated_data)
        return mcp_tool


class ToolsImportSerializer(serializers.Serializer):

    python_tools = PythonCodeToolImportSerializer(many=True)
    configured_tools = ToolConfigImportSerilizer(many=True)
    mcp_tools = McpToolImportSerializer(many=True)


class BaseConfigImportSerializer(serializers.ModelSerializer):

    model = serializers.CharField()

    class Meta:
        abstract = True
        fields = "__all__"
        extra_kwargs = {
            "custom_name": {"validators": []},
            "model": {"validators": []},
            "id": {"read_only": False, "required": False},
        }
        validators = []
        llm_model_class = LLMModel

    def create(self, validated_data):
        model_name = validated_data.pop("model")
        custom_name = validated_data.pop("custom_name")

        validated_data.pop("id", None)

        llm_model = self.get_llm_model(model_name)
        if not llm_model:
            raise serializers.ValidationError(
                {"model": f"Model '{model_name}' not found"}
            )

        existing_config = self.get_existing_config(
            model=model_name,
            custom_name=custom_name,
            validated_data=validated_data,
        )

        if existing_config:
            return existing_config

        provider = self.get_provider(llm_model)
        api_key = self.get_api_key(provider.name)

        if not self.Meta.model.objects.filter(custom_name=custom_name).exists():
            config = self.create_config(
                custom_name=custom_name,
                model=llm_model,
                api_key=api_key,
                validated_data=validated_data,
            )
            return config

        existing_names = self.Meta.model.objects.values_list("custom_name", flat=True)
        unique_name = generate_new_unique_name(custom_name, existing_names)

        config = self.create_config(
            custom_name=unique_name,
            model=llm_model,
            api_key=api_key,
            validated_data=validated_data,
        )
        return config

    def get_api_key(self, provider_name):
        api_key = (
            self.Meta.model.objects.filter(model__llm_provider__name=provider_name)
            .values_list("api_key", flat=True)
            .first()
        )
        return api_key

    def get_llm_model(self, model_name):
        llm_model = (
            self.Meta.llm_model_class.objects.filter(name=model_name)
            .select_related("llm_provider")
            .first()
        )
        return llm_model

    def get_provider(self, llm_model):
        return llm_model.llm_provider

    def create_config(self, custom_name, model, api_key, validated_data):
        return self.Meta.model.objects.create(
            custom_name=custom_name,
            model=model,
            api_key=api_key,
            **validated_data,
        )

    def get_existing_config(self, custom_name, model, validated_data):
        return self.Meta.model.objects.filter(
            model__name=model,
            custom_name=custom_name,
            **validated_data,
        ).first()


class LLMConfigImportSerializer(BaseConfigImportSerializer):

    class Meta(BaseConfigImportSerializer.Meta):
        model = LLMConfig

    def create(self, validated_data):
        model_name = validated_data.pop("model")
        custom_name = validated_data.pop("custom_name")

        validated_data.pop("id", None)

        llm_model = self.get_llm_model(model_name)
        if not llm_model:
            raise serializers.ValidationError(
                {"model": f"Model '{model_name}' not found"}
            )

        # Special case for JSON fields when they are None
        stop = validated_data.pop("stop", None)
        logit_bias = validated_data.pop("logit_bias", None)
        response_format = validated_data.pop("response_format", None)

        stop_filter = self.make_json_filter("stop", stop)
        logit_bias_filter = self.make_json_filter("logit_bias", logit_bias)
        response_format_filter = self.make_json_filter(
            "response_format", response_format
        )

        existing_config = self.Meta.model.objects.filter(
            stop_filter,
            response_format_filter,
            logit_bias_filter,
            model__name=model_name,
            custom_name=custom_name,
            **validated_data,
        ).first()

        if existing_config:
            return existing_config

        provider = self.get_provider(llm_model)
        api_key = self.get_api_key(provider.name)

        if not self.Meta.model.objects.filter(custom_name=custom_name).exists():
            config = self.Meta.model.objects.create(
                custom_name=custom_name,
                model=llm_model,
                api_key=api_key,
                **validated_data,
            )
            return config

        existing_names = self.Meta.model.objects.values_list("custom_name", flat=True)
        unique_name = generate_new_unique_name(custom_name, existing_names)

        config = self.Meta.model.objects.create(
            custom_name=unique_name,
            model=llm_model,
            api_key=api_key,
            **validated_data,
        )
        return config

    def make_json_filter(self, field_name, value):
        if value is None:
            return Q(**{f"{field_name}__isnull": True}) | Q(
                **{field_name: Value(None, output_field=JSONField())}
            )
        return Q(**{field_name: value})


class EmbeddingConfigImportSerializer(BaseConfigImportSerializer):

    class Meta(BaseConfigImportSerializer.Meta):
        model = EmbeddingConfig
        llm_model_class = EmbeddingModel

    def get_api_key(self, provider_name):
        api_key = (
            self.Meta.model.objects.filter(
                model__embedding_provider__name=provider_name
            )
            .values_list("api_key", flat=True)
            .first()
        )
        return api_key

    def get_llm_model(self, model_name):
        llm_model = (
            self.Meta.llm_model_class.objects.filter(name=model_name)
            .select_related("embedding_provider")
            .first()
        )
        return llm_model

    def get_provider(self, llm_model):
        return llm_model.embedding_provider


class RealtimeConfigImportSerializer(BaseConfigImportSerializer):

    class Meta(BaseConfigImportSerializer.Meta):
        model = RealtimeConfig
        llm_model_class = RealtimeModel
        fields = None
        exclude = ["api_key", "realtime_model"]

    def get_api_key(self, provider_name):
        api_key = (
            self.Meta.model.objects.filter(realtime_model__provider__name=provider_name)
            .values_list("api_key", flat=True)
            .first()
        )
        return api_key

    def get_llm_model(self, model_name):
        realtime_model = (
            self.Meta.llm_model_class.objects.filter(name=model_name)
            .select_related("provider")
            .first()
        )
        return realtime_model

    def get_provider(self, llm_model):
        return llm_model.provider

    def create_config(self, custom_name, model, api_key, validated_data):
        return self.Meta.model.objects.create(
            custom_name=custom_name,
            realtime_model=model,
            api_key=api_key,
            **validated_data,
        )

    def get_existing_config(self, custom_name, model, validated_data):
        return self.Meta.model.objects.filter(
            realtime_model__name=model,
            custom_name=custom_name,
            **validated_data,
        ).first()


class RealtimeTranscriptionConfigImportSerializer(BaseConfigImportSerializer):

    class Meta(BaseConfigImportSerializer.Meta):
        model = RealtimeTranscriptionConfig
        llm_model_class = RealtimeTranscriptionModel
        fields = None
        exclude = ["api_key", "realtime_transcription_model"]

    def get_api_key(self, provider_name):
        api_key = (
            self.Meta.model.objects.filter(
                realtime_transcription_model__provider__name=provider_name
            )
            .values_list("api_key", flat=True)
            .first()
        )
        return api_key

    def get_llm_model(self, model_name):
        realtime_model = (
            self.Meta.llm_model_class.objects.filter(name=model_name)
            .select_related("provider")
            .first()
        )
        return realtime_model

    def get_provider(self, llm_model):
        return llm_model.provider

    def create_config(self, custom_name, model, api_key, validated_data):
        return self.Meta.model.objects.create(
            custom_name=custom_name,
            realtime_transcription_model=model,
            api_key=api_key,
            **validated_data,
        )

    def get_existing_config(self, custom_name, model, validated_data):
        return self.Meta.model.objects.filter(
            realtime_transcription_model__name=model,
            custom_name=custom_name,
            **validated_data,
        ).first()


class RealtimeAgentImportSerializer(serializers.ModelSerializer):

    realtime_config = RealtimeConfigImportSerializer(required=False, allow_null=True)
    realtime_transcription_config = RealtimeTranscriptionConfigImportSerializer(
        required=False, allow_null=True
    )

    class Meta:
        model = RealtimeAgent
        exclude = ["agent"]

    def create(self, validated_data):
        agent = self.context.get("agent")
        if not agent:
            raise serializers.ValidationError(
                "RealtimeAgent cannot be created without agent"
            )

        realtime_config = validated_data.pop("realtime_config", None)
        transcription_config = validated_data.pop("realtime_transcription_config", None)
        realtime_config_id = realtime_config.get("id") if realtime_config else None
        transcription_config_id = (
            transcription_config.get("id") if transcription_config else None
        )

        configs_service = None
        transcription_configs_service = None

        if realtime_config:
            configs_service = RealtimeConfigsImportService([realtime_config])
            configs_service.create_configs()
        if transcription_config:
            transcription_configs_service = RealtimeTranscriptionConfigsImportService(
                [transcription_config]
            )
            transcription_configs_service.create_configs()

        realtime_agent, _ = RealtimeAgent.objects.get_or_create(
            agent=agent, **validated_data
        )

        if configs_service:
            realtime_agent.realtime_config = configs_service.get_config(
                realtime_config_id
            )
        if transcription_configs_service:
            realtime_agent.realtime_transcription_config = (
                transcription_configs_service.get_config(transcription_config_id)
            )

        realtime_agent.save()
        return realtime_agent


class NestedRealtimeAgentImportSerializer(RealtimeAgentImportSerializer):

    id = serializers.IntegerField()
    realtime_config = serializers.IntegerField(required=False, allow_null=True)
    realtime_transcription_config = serializers.IntegerField(
        required=False, allow_null=True
    )

    class Meta(RealtimeAgentImportSerializer.Meta):
        extra_kwargs = {
            "id": {"required": False, "read_only": False, "validators": []},
        }


class RealtimeDataImportSerializer(serializers.Serializer):

    realtime_configs = RealtimeConfigImportSerializer(many=True)
    realtime_transcription_configs = RealtimeTranscriptionConfigImportSerializer(
        many=True
    )
    realtime_agents = NestedRealtimeAgentImportSerializer(many=True)

    def create(self, validated_data):
        agents = self.context.get("mapped_agents", {})

        realtime_configs = validated_data.pop("realtime_configs", [])
        realtime_transcription_configs = validated_data.pop(
            "realtime_transcription_configs", []
        )
        realtime_agents = validated_data.pop("realtime_agents", [])

        realtime_agents_service = RealtimeAgentImportService(realtime_agents)
        configs_service = None
        transcription_configs_service = None

        if realtime_configs:
            configs_service = RealtimeConfigsImportService(realtime_configs)
            configs_service.create_configs()
        if realtime_transcription_configs:
            transcription_configs_service = RealtimeTranscriptionConfigsImportService(
                realtime_transcription_configs
            )
            transcription_configs_service.create_configs()

        realtime_agents_service.create_agents(
            agents=agents,
            rt_config_service=configs_service,
            rt_transcription_config_service=transcription_configs_service,
        )


class AgentImportSerializer(serializers.ModelSerializer):

    llm_config = LLMConfigImportSerializer(required=False, allow_null=True)
    fcm_llm_config = LLMConfigImportSerializer(required=False, allow_null=True)
    realtime_agent = RealtimeAgentImportSerializer(required=False, allow_null=True)
    tools = ToolsImportSerializer(required=False)

    class Meta:
        model = Agent
        exclude = [
            "tags",
            "knowledge_collection",
        ]
        extra_kwargs = {
            "tools": {"validators": []},
            "id": {"read_only": False, "required": False, "validators": []},
        }

    def create(self, validated_data):
        validated_data.pop("id", None)
        tools_data = validated_data.pop("tools", [])
        realtime_agent_data = validated_data.pop("realtime_agent", None)

        configs = []
        config_service = None

        llm_config = validated_data.pop("llm_config", {})
        fcm_llm_config = validated_data.pop("fcm_llm_config", {})
        llm_config_id = llm_config.get("id") if llm_config else None
        fcm_config_id = fcm_llm_config.get("id") if fcm_llm_config else None

        if llm_config:
            configs.append(llm_config)
        if fcm_llm_config:
            configs.append(fcm_llm_config)

        if configs:
            config_service = LLMConfigsImportService(configs)
            config_service.create_configs()

        agent = Agent.objects.create(**validated_data)

        if config_service:
            agent.llm_config = config_service.get_config(llm_config_id)
            agent.fcm_llm_config = config_service.get_config(fcm_config_id)
            agent.save()

        if realtime_agent_data and not isinstance(realtime_agent_data, int):
            realtime_agent_serializer = RealtimeAgentImportSerializer(
                data=realtime_agent_data, context={"agent": agent}
            )
            realtime_agent_serializer.is_valid(raise_exception=True)
            realtime_agent_serializer.save()

        if tools_data:
            tools_ids = self._get_tools_ids(tools_data)
            tools_service = ToolsImportService(tools=tools_data)
            tools_service.create_tools()
            tools_service.assign_tools_to_agent(agent, tools_ids)

        return agent

    def _get_tools_ids(self, tools_data):
        return {
            "python_tools": [t_data["id"] for t_data in tools_data["python_tools"]],
            "configured_tools": [
                t_data["id"] for t_data in tools_data["configured_tools"]
            ],
            "mcp_tools": [t_data["id"] for t_data in tools_data["mcp_tools"]],
        }


class NestedAgentImportSerializer(AgentImportSerializer):

    tools = serializers.DictField(required=False)
    llm_config = serializers.IntegerField(required=False, allow_null=True)
    fcm_llm_config = serializers.IntegerField(required=False, allow_null=True)
    realtime_agent = serializers.IntegerField(required=False, allow_null=True)


class TaskImportSerializer(serializers.ModelSerializer):

    agent = serializers.IntegerField(required=False, allow_null=True)
    tools = serializers.DictField(required=False, allow_null=True)
    context_tasks = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_null=True
    )

    class Meta:
        model = Task
        exclude = ["crew"]
        extra_kwargs = {"id": {"required": False, "read_only": False}}
        validators = []

    def create(self, validated_data):
        crew = self.context.get("crew")
        if not crew:
            raise serializers.ValidationError("Task cannot be created without crew")

        return Task.objects.create(crew=crew, **validated_data)


class CrewImportSerializer(serializers.ModelSerializer):

    tasks = TaskImportSerializer(many=True, required=False)
    agents = NestedAgentImportSerializer(many=True, required=False)
    tools = ToolsImportSerializer(required=False)
    embedding_config = EmbeddingConfigImportSerializer(required=False, allow_null=True)
    memory_llm_config = serializers.IntegerField(required=False, allow_null=True)
    manager_llm_config = serializers.IntegerField(required=False, allow_null=True)
    planning_llm_config = serializers.IntegerField(required=False, allow_null=True)
    llm_configs = LLMConfigImportSerializer(many=True, required=False, allow_null=True)
    realtime_agents = RealtimeDataImportSerializer(required=False, allow_null=True)

    agent_serializer_class = NestedAgentImportSerializer

    class Meta:
        model = Crew
        exclude = ["id", "tags", "knowledge_collection"]

    def create(self, validated_data):
        memory_llm_config_id = validated_data.pop("memory_llm_config", None)
        manager_llm_config_id = validated_data.pop("manager_llm_config", None)
        planning_llm_config_id = validated_data.pop("planning_llm_config", None)

        configs_data = validated_data.pop("llm_configs", [])
        llm_configs_service = LLMConfigsImportService(configs_data)
        llm_configs_service.create_configs()

        new_agents = {}
        agents_data = validated_data.pop("agents", [])
        realtime_agents_data = validated_data.pop("realtime_agents", [])
        tasks_data = validated_data.pop("tasks", [])
        tools_data = validated_data.pop("tools", [])
        embedding_config_data = validated_data.pop("embedding_config", None)
        embedding_config = None
        tools_service = None

        tasks_service = TasksImportService()

        if embedding_config_data:
            embedding_config = EmbeddingConfigImportSerializer().create(
                embedding_config_data
            )

        name = validated_data.pop("name")
        unqiue_name = generate_new_unique_name(
            name,
            Crew.objects.values_list("name", flat=True),
        )

        crew = Crew.objects.create(
            embedding_config=embedding_config,
            memory_llm_config=llm_configs_service.get_config(memory_llm_config_id),
            manager_llm_config=llm_configs_service.get_config(manager_llm_config_id),
            planning_llm_config=llm_configs_service.get_config(planning_llm_config_id),
            name=unqiue_name,
            **validated_data,
        )
        if tools_data:
            tools_service = ToolsImportService(tools_data)
            tools_service.create_tools()

        for a_data in agents_data:
            tool_ids_data = a_data.pop("tools", {})
            llm_config_id = a_data.pop("llm_config", None)
            fcm_llm_config_id = a_data.pop("fcm_llm_config", None)

            current_id = a_data.pop("id")

            agent_serializer = self.agent_serializer_class(data=a_data)
            agent_serializer.is_valid(raise_exception=True)
            agent = agent_serializer.save()

            agent.llm_config = llm_configs_service.get_config(llm_config_id)
            agent.fcm_llm_config = llm_configs_service.get_config(fcm_llm_config_id)
            agent.save()

            if tools_service:
                tools_service.assign_tools_to_agent(agent, tool_ids_data)

            new_agents[current_id] = agent

        agents = new_agents.values()
        if agents:
            crew.agents.set(agents)

        if realtime_agents_data:
            realtime_agents_serializer = RealtimeDataImportSerializer(
                context={"mapped_agents": new_agents}
            )
            realtime_agents_serializer.create(realtime_agents_data)

        for t_data in tasks_data:
            tool_ids_data = t_data.pop("tools", {})
            context_ids = t_data.pop("context_tasks", [])
            agent_id = t_data.pop("agent", None)

            task = tasks_service.create_task(t_data, crew)

            if agent_id:
                agent = new_agents.get(agent_id)
                task.agent = agent
                task.save()

            tasks_service.add_task_context(task, context_ids)
            if tools_service:
                tools_service.assign_tools_to_task(task, tool_ids_data)

        return crew


class NestedCrewImportSerializer(CrewImportSerializer):

    tools = None
    llm_configs = None
    realtime_agents = None
    agents = serializers.ListField(child=serializers.IntegerField(), required=False)

    class Meta(CrewImportSerializer.Meta):
        exclude = ["tags", "knowledge_collection"]
        extra_kwargs = {
            "id": {"read_only": False, "required": False, "validators": []},
        }


class CrewNodeImportSerializer(serializers.ModelSerializer):

    crew_id = serializers.IntegerField()

    class Meta:
        model = CrewNode
        exclude = ["graph", "crew"]

    def create(self, validated_data):
        data = {"graph": self.context.get("graph"), **validated_data}
        return super().create(data)


class PythonNodeImportSerializer(PythonNodeSerializer):

    python_code = PythonCodeImportSerializer()
    graph = None

    class Meta(PythonNodeSerializer.Meta):
        fields = None
        exclude = ["graph"]

    def create(self, validated_data):
        data = {"graph": self.context.get("graph"), **validated_data}
        return super().create(data)


class StartNodeImportSerializer(StartNodeSerializer):

    class Meta(StartNodeSerializer.Meta):
        fields = None
        exclude = ["graph"]

    def create(self, validated_data):
        data = {"graph": self.context.get("graph"), **validated_data}
        return super().create(data)


class EndNodeImportSerializer(EndNodeSerializer):

    graph = None

    class Meta(EndNodeSerializer.Meta):
        fields = None
        exclude = ["graph"]
        validators = []

    def create(self, validated_data):
        data = {"graph": self.context.get("graph"), **validated_data}
        return super().create(data)


class FileExtractorNodeImportSerializer(FileExtractorNodeSerializer):

    graph = None

    class Meta(FileExtractorNodeSerializer.Meta):
        fields = None
        exclude = ["graph"]
        validators = []

    def create(self, validated_data):
        data = {"graph": self.context.get("graph"), **validated_data}
        return super().create(data)


class EdgeImportSerializer(EdgeSerializer):

    graph = None

    class Meta(EdgeSerializer.Meta):
        fields = None
        exclude = ["graph"]
        validators = []

    def create(self, validated_data):
        data = {"graph": self.context.get("graph"), **validated_data}
        return super().create(data)


class ConditionalEdgeImportSerializer(ConditionalEdgeSerializer):

    python_code = PythonCodeImportSerializer()

    class Meta(ConditionalEdgeSerializer.Meta):
        fields = None
        exclude = ["graph"]
        validators = []

    def create(self, validated_data):
        data = {"graph": self.context.get("graph"), **validated_data}
        return super().create(data)


class MetdataNodeSerializer(serializers.Serializer):

    id = serializers.CharField(required=True)
    data = serializers.JSONField(required=False, allow_null=True)
    icon = serializers.CharField()
    size = serializers.DictField()
    type = serializers.CharField()
    color = serializers.CharField()
    ports = serializers.DictField(allow_null=True)
    category = serializers.CharField()
    parentId = serializers.CharField(allow_null=True, allow_blank=True)
    position = serializers.DictField()
    input_map = serializers.DictField()
    node_name = serializers.CharField(allow_null=True)
    output_variable_path = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )

    def create(self, validated_data):
        mapped_crews = self.context.get("mapped_crews")
        mapped_node_names = self.context.get("mapped_node_names")

        type_ = validated_data.get("type")
        data = validated_data.pop("data", {})

        if type_ == "project":
            crew_id = data.get("id")
            crew = mapped_crews.get(crew_id)
            node_name = validated_data.pop("node_name")
            node_name = mapped_node_names.get(node_name)

            crew_data = NestedCrewExportSerializer(instance=crew).data
            crew_data["tasks"] = [task["id"] for task in crew_data["tasks"]]

            return {"data": crew_data, "node_name": node_name, **validated_data}

        if type_ == "python":
            node_name = validated_data.pop("node_name")
            node_name = mapped_node_names.get(node_name)
            return {"node_name": node_name, "data": data, **validated_data}

        return {"data": data, **validated_data}


class GraphMetadataSerializer(serializers.Serializer):

    nodes = MetdataNodeSerializer(many=True, required=False)
    groups = serializers.JSONField(required=False)
    connections = serializers.JSONField(required=False)

    def create(self, validated_data):
        nodes_data = validated_data.pop("nodes", [])
        mapped_crews = self.context.get("mapped_crews")
        mapped_node_names = self.context.get("mapped_node_names")

        nodes_serializer = MetdataNodeSerializer(
            data=nodes_data,
            many=True,
            context={
                "mapped_crews": mapped_crews,
                "mapped_node_names": mapped_node_names,
            },
        )
        nodes_serializer.is_valid(raise_exception=True)
        nodes = nodes_serializer.save()

        connections = validated_data.pop("connections", {})
        groups = validated_data.pop("groups", {})

        return {"nodes": nodes, "groups": groups, "connections": connections}


class GraphImportSerializer(serializers.ModelSerializer):

    crews = NestedCrewImportSerializer(
        many=True, required=False, allow_null=False, default=dict
    )
    agents = NestedAgentImportSerializer(
        many=True, required=False, allow_null=False, default=dict
    )
    tools = ToolsImportSerializer(required=False, allow_null=False, default=dict)
    llm_configs = LLMConfigImportSerializer(
        many=True, required=False, allow_null=False, default=dict
    )
    realtime_agents = RealtimeDataImportSerializer(
        required=False, allow_null=False, default=dict
    )

    crew_node_list = CrewNodeImportSerializer(many=True)
    python_node_list = PythonNodeImportSerializer(many=True)
    edge_list = EdgeImportSerializer(many=True)
    conditional_edge_list = ConditionalEdgeImportSerializer(many=True)
    start_node_list = StartNodeImportSerializer(many=True)
    file_extractor_node_list = FileExtractorNodeImportSerializer(
        many=True, required=False
    )
    end_node_list = EndNodeImportSerializer(many=True, required=False)
    # llm_node_list = LLMNodeSerializer(many=True)
    # decision_table_node_list = DecisionTableNodeSerializer(many=True)

    metadata = GraphMetadataSerializer()

    agent_serializer_class = NestedAgentImportSerializer
    crew_serializer_class = NestedCrewImportSerializer

    class Meta:
        model = Graph
        exclude = ["id", "tags"]

    def create(self, validated_data):
        crews_data = validated_data.pop("crews", [])
        agents_data = validated_data.pop("agents", [])
        tools_data = validated_data.pop("tools", [])
        llm_configs_data = validated_data.pop("llm_configs", [])
        realtime_agents_data = validated_data.pop("realtime_agents", {})

        crew_node_list_data = validated_data.pop("crew_node_list", [])
        python_node_list_data = validated_data.pop("python_node_list", [])
        edge_list_data = validated_data.pop("edge_list", [])
        conditional_edge_list_data = validated_data.pop("conditional_edge_list", [])
        start_node_list_data = validated_data.pop("start_node_list", [])
        end_node_list_data = validated_data.pop("end_node_list", [])
        file_extractor_node_list_data = validated_data.pop(
            "file_extractor_node_list", []
        )
        # llm_node_list_data = validated_data.pop("llm_node_list", [])
        # decision_table_node_list_data = validated_data.pop(
        #     "decision_table_node_list", []
        # )

        metadata = validated_data.pop("metadata", {})

        tools_service = None
        agents_service = None
        crews_service = None
        llm_configs_service = None

        previous_name = validated_data.pop("name")
        unique_name = generate_new_unique_name(
            previous_name,
            Graph.objects.values_list("name", flat=True),
        )
        graph = Graph.objects.create(name=unique_name, **validated_data)
        # Store previous node names and map those to new node names
        mapped_node_names = {}

        if tools_data:
            tools_service = ToolsImportService(tools_data)
            tools_service.create_tools()

        if llm_configs_data:
            llm_configs_service = LLMConfigsImportService(llm_configs_data)
            llm_configs_service.create_configs()

        if agents_data:
            agents_service = AgentsImportService(
                agents_data, self.agent_serializer_class
            )
            agents_service.create_agents(tools_service, llm_configs_service)

        if realtime_agents_data and agents_data:
            realtime_agents_serializer = RealtimeDataImportSerializer(
                context={"mapped_agents": agents_service.mapped_agents}
            )
            realtime_agents_serializer.create(realtime_agents_data)

        if crews_data:
            crews_service = CrewsImportService(crews_data, self.crew_serializer_class)
            crews_service.create_crews(
                agents_service, tools_service, llm_configs_service
            )

        for node_data in crew_node_list_data:
            crew_id = node_data.pop("crew_id", None)
            crew = crews_service.mapped_crews.get(crew_id)

            previous_name = node_data.pop("node_name")
            mapped_node_names[previous_name] = previous_name

            data = {
                "crew_id": crew.id,
                "node_name": mapped_node_names[previous_name],
                **node_data,
            }

            serializer = CrewNodeImportSerializer(data=data, context={"graph": graph})
            serializer.is_valid(raise_exception=True)
            serializer.save()

        for node_data in python_node_list_data:
            previous_name = node_data.pop("node_name")
            mapped_node_names[previous_name] = previous_name

            serializer = PythonNodeImportSerializer(
                data=node_data, context={"graph": graph}
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        for node_data in start_node_list_data:
            serializer = StartNodeImportSerializer(
                data=node_data, context={"graph": graph}
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        for node_data in end_node_list_data:
            serializer = EndNodeImportSerializer(
                data=node_data, context={"graph": graph}
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        for node_data in file_extractor_node_list_data:
            serializer = FileExtractorNodeImportSerializer(
                data=node_data, context={"graph": graph}
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        for edge_data in edge_list_data:
            start_key = edge_data.pop("start_key", None)
            end_key = edge_data.pop("end_key", None)

            mapped_key = mapped_node_names.get(start_key)
            if mapped_key:
                start_key = mapped_key

            mapped_key = mapped_node_names.get(end_key)
            if mapped_key:
                end_key = mapped_key

            data = {"start_key": start_key, "end_key": end_key, **edge_data}
            serializer = EdgeImportSerializer(data=data, context={"graph": graph})
            serializer.is_valid(raise_exception=True)
            serializer.save()

        for edge_data in conditional_edge_list_data:
            serializer = ConditionalEdgeImportSerializer(
                data=edge_data, context={"graph": graph}
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        context = {"mapped_node_names": mapped_node_names}
        if crews_service:
            context["mapped_crews"] = crews_service.mapped_crews

        metadata_serializer = GraphMetadataSerializer(data=metadata, context=context)
        metadata_serializer.is_valid(raise_exception=True)
        graph.metadata = metadata_serializer.save()
        graph.save()

        return graph
