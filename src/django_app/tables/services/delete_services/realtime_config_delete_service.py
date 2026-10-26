from rbac.models.enums import ResourceType
from tables.models.realtime_models import (
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    OpenAIRealtimeConfig,
    RealtimeAgentDefinition,
)
from tables.services.delete_services.base_delete_service import BaseDeleteService
from tables.services.delete_services.usage import (
    BucketCollector,
    UsageReport,
    build_reports,
)


class _ProviderRealtimeConfigDeleteService(BaseDeleteService):
    """Realtime provider config delete: usage is the agents configured to use it.

    Subclasses set `model` and the FK name `config_field`. `RealtimeAgentChat` is
    not counted: a session snapshot is a record of past use, not a dependency.
    """

    config_field: str

    def collect_usage(self, ids: list[int]) -> dict[int, UsageReport]:
        """The agents configured to use each config."""
        agents = BucketCollector.for_resource(ResourceType.AGENTS, self.permissions)

        if ids:
            column = f"{self.config_field}_id"
            agents.add_rows(
                RealtimeAgentDefinition.objects.filter(
                    agent_definition__org_id=self.org_id, **{f"{column}__in": ids}
                ).values_list(column, "agent_definition_id", "agent_definition__name")
            )

        return build_reports(ids, [agents])


class OpenAIRealtimeConfigDeleteService(_ProviderRealtimeConfigDeleteService):
    """Delete service for OpenAIRealtimeConfig entities."""

    model = OpenAIRealtimeConfig
    config_field = "openai_config"


class ElevenLabsRealtimeConfigDeleteService(_ProviderRealtimeConfigDeleteService):
    """Delete service for ElevenLabsRealtimeConfig entities."""

    model = ElevenLabsRealtimeConfig
    config_field = "elevenlabs_config"


class GeminiRealtimeConfigDeleteService(_ProviderRealtimeConfigDeleteService):
    """Delete service for GeminiRealtimeConfig entities."""

    model = GeminiRealtimeConfig
    config_field = "gemini_config"
