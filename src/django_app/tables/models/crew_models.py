from typing import Any
from django.db import models
from django.db.models import CheckConstraint
from tables.models import DefaultBaseModel, AbstractDefaultFillableModel, Process
from django.core.exceptions import ValidationError


class DefaultCrewConfig(DefaultBaseModel):

    embedding_config = models.ForeignKey(
        "EmbeddingConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
    )
    manager_llm_config = models.ForeignKey(
        "LLMConfig",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        default=None,
        related_name="default_manager_crews",
    )
    process = models.CharField(
        max_length=255, choices=Process.choices, default=Process.SEQUENTIAL
    )
    memory = models.BooleanField(default=False)
    max_rpm = models.IntegerField(null=True, default=100)
    cache = models.BooleanField(default=False)
    default_temperature = models.FloatField(default=0.7, null=False)

    def __str__(self):
        return "Default Crew Config"


class DefaultAgentConfig(DefaultBaseModel):

    max_iter = models.IntegerField(null=True, default=20)
    max_rpm = models.IntegerField(null=True, default=100)
    max_execution_time = models.IntegerField(null=True, default=True)
    memory = models.BooleanField(default=False)
    allow_delegation = models.BooleanField(default=False)
    cache = models.BooleanField(default=False)
    allow_code_execution = models.BooleanField(default=False)
    max_retry_limit = models.IntegerField(default=2)
    respect_context_window = models.BooleanField(default=True)
    default_temperature = models.FloatField(default=0.8, null=False)

    llm_config = models.ForeignKey(
        "LLMConfig",
        on_delete=models.SET_NULL,
        related_name="default_agent_config",
        null=True,
        default=None,
    )
    fcm_llm_config = models.ForeignKey(
        "LLMConfig",
        on_delete=models.SET_NULL,
        related_name="default_agent_fcm_config",
        null=True,
        default=None,
    )

    def get_default_temperature(self) -> int:
        return self.default_temperature or DefaultCrewConfig.load().default_temperature

    def __str__(self):
        return "Default Agent Config"


class Agent(AbstractDefaultFillableModel):
    tags = models.ManyToManyField(to="AgentTag", blank=True, default=[])
    role = models.TextField()
    goal = models.TextField()
    backstory = models.TextField()
    configured_tools = models.ManyToManyField("ToolConfig", blank=True, default=[])
    python_code_tools = models.ManyToManyField("PythonCodeTool", blank=True, default=[])
    max_iter = models.IntegerField(default=None, null=True)
    max_rpm = models.IntegerField(default=None, null=True)
    max_execution_time = models.IntegerField(default=None, null=True)
    memory = models.BooleanField(default=None, null=True)
    allow_delegation = models.BooleanField(default=None, null=True)
    cache = models.BooleanField(default=None, null=True)
    allow_code_execution = models.BooleanField(default=None, null=True)
    max_retry_limit = models.IntegerField(default=None, null=True)
    respect_context_window = models.BooleanField(default=None, null=True)
    default_temperature = models.FloatField(default=None, null=True)
    knowledge_collection = models.ForeignKey(
        "SourceCollection", on_delete=models.SET_NULL, blank=True, null=True
    )

    llm_config = models.ForeignKey(
        "LLMConfig",
        on_delete=models.SET_NULL,
        null=True,
        related_name="llm_agents",
        default=None,
    )
    fcm_llm_config = models.ForeignKey(
        "LLMConfig",
        on_delete=models.SET_NULL,
        null=True,
        related_name="fcm_agents",
        default=None,
    )

    def get_default_model(self):
        return DefaultAgentConfig.load()

    def fill_with_defaults(self):
        super().fill_with_defaults()
        self.default_temperature = self.get_default_temperature()

        if self.llm_config is not None:

            if self.llm_config.temperature is None:
                self.llm_config.temperature = self.default_temperature

        if self.fcm_llm_config is not None:
            if self.fcm_llm_config.temperature is None:
                self.fcm_llm_config.temperature = self.default_temperature

        return self

    def get_default_temperature(self) -> int:
        return (
            self.default_temperature
            or DefaultAgentConfig.load().get_default_temperature()
        )

    def __str__(self):
        return self.role


class Crew(AbstractDefaultFillableModel):
    metadata = models.JSONField(default=dict)
    tags = models.ManyToManyField(to="CrewTag", blank=True, default=[])
    description = models.TextField(null=True, blank=True)
    name = models.TextField()
    agents = models.ManyToManyField(Agent, blank=True)
    process = models.CharField(
        max_length=255, choices=Process.choices, default=Process.SEQUENTIAL
    )
    memory = models.BooleanField(null=True, default=None)
    memory_llm_config = models.ForeignKey(
        "LLMConfig",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        default=None,
        related_name="memory_llm_config",
    )
    embedding_config = models.ForeignKey(
        "EmbeddingConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
    )
    manager_llm_config = models.ForeignKey(
        "LLMConfig",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        default=None,
        related_name="manager_crews",
    )
    config = models.JSONField(null=True, blank=True)
    max_rpm = models.IntegerField(null=True, default=None)
    cache = models.BooleanField(null=True, default=None)
    full_output = models.BooleanField(default=False)
    planning = models.BooleanField(default=False)
    planning_llm_config = models.ForeignKey(
        "LLMConfig",
        default=None,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="planning_llm_config",
    )
    default_temperature = models.FloatField(null=True, default=None)
    knowledge_collection = models.ForeignKey(
        "SourceCollection", on_delete=models.SET_NULL, blank=True, null=True
    )

    def get_default_model(self):
        return DefaultCrewConfig.load()

    def fill_with_defaults(self):
        super().fill_with_defaults()
        self.default_temperature = self.get_default_temperature()

        if self.manager_llm_config is not None:
            if self.manager_llm_config.temperature is None:
                self.manager_llm_config.temperature = self.default_temperature

        if self.planning_llm_config is not None:
            if self.planning_llm_config.temperature is None:
                self.planning_llm_config.temperature = self.default_temperature

        self.agents.set(self.get_agents())
        return self

    def get_agents(self):
        agent_list: list[Agent] = []
        for agent in self.agents.all():
            agent: Agent
            # set agent default temperature or crew default temperature
            if agent.default_temperature is None:
                agent.default_temperature = self.get_default_temperature()

            agent.fill_with_defaults()
            agent_list.append(agent)
        return agent_list

    def get_default_temperature(self):
        if self.default_temperature is not None:
            return self.default_temperature
        return DefaultCrewConfig.load().default_temperature

    def __str__(self):
        return self.name


class ToolConfigField(models.Model):
    class FieldType(models.TextChoices):
        LLM_CONFIG = "llm_config"
        EMBEDDING_CONFIG = "embedding_config"
        STRING = "string"
        BOOLEAN = "boolean"
        ANY = "any"
        INTEGER = "integer"
        FLOAT = "float"

    tool = models.ForeignKey(
        "Tool", on_delete=models.CASCADE, null=True, related_name="tool_fields"
    )

    title = models.CharField(blank=True, null=False, max_length=255, default="")

    name = models.CharField(blank=False, null=False, max_length=255)
    description = models.TextField(blank=True)
    data_type = models.CharField(
        choices=FieldType.choices,
        max_length=255,
        blank=False,
        null=False,
        default=FieldType.STRING,
    )
    required = models.BooleanField(default=True)

    class Meta:
        unique_together = (
            "tool",
            "name",
        )


class Tool(models.Model):
    name = models.TextField()
    name_alias = models.TextField()
    description = models.TextField()
    enabled = models.BooleanField(default=True)
    favorite = models.BooleanField(default=False)

    def __str__(self):
        return self.description

    def get_tool_config_fields(self) -> dict[str, "ToolConfigField"]:
        return {
            field.name: field for field in ToolConfigField.objects.filter(tool=self)
        }


class ToolConfig(models.Model):
    name = models.CharField(blank=False, null=False, max_length=255)
    tool = models.ForeignKey("Tool", on_delete=models.CASCADE)
    configuration = models.JSONField(default=dict)

    def get_tool_config_field(self, name: str) -> ToolConfigField:
        return ToolConfigField.objects.filter(tool=self.tool, name=name).first()


class DefaultToolConfig(DefaultBaseModel):
    llm_config = models.ForeignKey(
        "LLMConfig",
        on_delete=models.SET_NULL,
        null=True,
        related_name="default_tool_llm_config",
        default=None,
    )
    embedding_config = models.ForeignKey(
        "EmbeddingConfig",
        on_delete=models.SET_NULL,
        null=True,
        related_name="default_tool_embedding_config",
        default=None,
    )

    def __str__(self):
        return "Default Tool Config"


class TemplateAgent(models.Model):
    role = models.TextField()
    goal = models.TextField()
    backstory = models.TextField()
    configured_tools = models.ManyToManyField(ToolConfig, blank=True, default=[])
    allow_delegation = models.BooleanField(default=False)
    memory = models.BooleanField(default=False)
    max_iter = models.IntegerField(default=25)

    llm_config = models.ForeignKey(
        "LLMConfig",
        on_delete=models.SET_NULL,
        null=True,
        related_name="llm_template_agents",
        default=None,
    )
    fcm_llm_config = models.ForeignKey(
        "LLMConfig",
        on_delete=models.SET_NULL,
        null=True,
        related_name="fcm_template_agents",
        default=None,
    )

    def __str__(self):
        return self.role


class Task(models.Model):
    crew = models.ForeignKey("Crew", on_delete=models.SET_NULL, null=True, default=None)
    name = models.TextField()
    agent = models.ForeignKey(
        "Agent", on_delete=models.SET_NULL, null=True, default=None
    )
    instructions = models.TextField()
    expected_output = models.TextField()
    order = models.IntegerField(null=True, default=None)
    human_input = models.BooleanField(default=False)
    async_execution = models.BooleanField(default=False)
    config = models.JSONField(null=True, blank=True)
    output_model = models.JSONField(null=True, default=None)

    def __str__(self):
        return self.name


class TaskConfiguredTools(models.Model):
    task = models.ForeignKey(
        "Task", on_delete=models.CASCADE, related_name="task_configured_tool_list"
    )
    tool = models.ForeignKey(ToolConfig, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("task", "tool")


class TaskPythonCodeTools(models.Model):
    task = models.ForeignKey(
        "Task", on_delete=models.CASCADE, related_name="task_python_code_tool_list"
    )
    tool = models.ForeignKey("PythonCodeTool", on_delete=models.CASCADE)

    class Meta:
        unique_together = ("task", "tool")


class TaskContext(models.Model):
    task = models.ForeignKey(
        "Task", on_delete=models.CASCADE, related_name="task_context_list"
    )
    context = models.ForeignKey(
        "Task", on_delete=models.CASCADE, related_name="context_task_list"
    )

    class Meta:
        unique_together = ("task", "context")
        constraints = [
            CheckConstraint(
                check=~models.Q(task=models.F("context")), name="task_not_equal_context"
            )
        ]

    def clean(self):
        super().clean()
        if self.task.order is not None and self.context.order is not None:
            if self.context.order >= self.task.order:
                raise ValidationError(
                    "Context task order must be lower than the main task order"
                )

        if self.task_id == self.context_id:
            raise ValidationError("A task cannot be assigned as its own context.")


def set_field_value_null_in_tool_configs(field_type: str, value: Any):
    # Get all fields with type `field_type`
    field_set = ToolConfigField.objects.filter(data_type=field_type)
    for field in field_set:
        # Get this field's tool
        tool = field.tool
        # Get all tool configs for this tool
        tool_config_set = ToolConfig.objects.filter(tool=tool)
        for tool_config in tool_config_set:

            # Set configuration key to None if current value match
            if not tool_config.configuration.get(field.name):
                # if config not set then skip setting None
                continue

            if tool_config.configuration[field.name] == value:
                tool_config.configuration[field.name] = None
                tool_config.save()
