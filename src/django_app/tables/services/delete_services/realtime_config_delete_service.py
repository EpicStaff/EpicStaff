from tables.models.rbac_models.rbac_enums import ResourceType
from tables.models.realtime_models import (
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    OpenAIRealtimeConfig,
    RealtimeAgent,
    RealtimeAgentDefinition,
)
from tables.services.delete_services.base_delete_service import BaseDeleteService
from tables.services.delete_services.usage import (
    BucketCollector,
    RefKind,
    UsageReport,
    build_reports,
)
from tables.services.rbac.effective_permissions import EffectivePermissions


class _ProviderRealtimeConfigDeleteService(BaseDeleteService):
    """Shared by the three live realtime provider configs.

    It sets no `model`, so it stays abstract; only the three subclasses below
    can be instantiated.

    They differ only in model and in the name of the FK pointing at them, and
    that FK has the same name on every referencing model -- so one
    `collect_usage`, parametrised by `config_field`, serves all three.

    Usage is one AGENTS bucket fed by two models, both primary-keyed on the
    agent they extend, so the reference id *is* the agent id:

    - `RealtimeAgent` -> the deprecated `tables.Agent` (`kind="agent"`). Still
      counted: existing flows with a CrewNode keep executing.
    - `RealtimeAgentDefinition` -> `agents.AgentDefinition`
      (`kind="agent_definition"`).

    `tables.Agent` and `AgentDefinition` ids come from different sequences, which
    is why references are keyed on `(kind, id)`.

    `RealtimeAgentChat` is deliberately **not** counted, though it also holds an
    FK to the config. It is a session snapshot: it copies wake word, voice,
    language and the rest precisely so it survives the config going away. A
    record *of* past use is not a dependency. Counting it would not preserve
    history either -- the FK is SET_NULL, so a caller who can see the chats
    could still delete and null every link after a warning; it would only make
    configs undeletable for callers who cannot. Accepted loss: `model_name`
    lives on the config and is not snapshotted, so a past session stops showing
    which model it used once its config is deleted. The agent link survives.
    """

    config_field: str

    def collect_usage(
        self, ids: list[int], org_id: int, effective: EffectivePermissions
    ) -> dict[int, UsageReport]:
        """The live agents, legacy and current, configured to use each config."""
        agents = BucketCollector.for_resource(ResourceType.AGENTS, effective)

        if ids:
            column = f"{self.config_field}_id"
            agents.add_rows(
                RealtimeAgent.objects.filter(
                    agent__org_id=org_id, **{f"{column}__in": ids}
                ).values_list(column, "agent_id", "agent__role"),
                kind=RefKind.AGENT,
            )
            agents.add_rows(
                RealtimeAgentDefinition.objects.filter(
                    agent_definition__organization_id=org_id, **{f"{column}__in": ids}
                ).values_list(column, "agent_definition_id", "agent_definition__name"),
                kind=RefKind.AGENT_DEFINITION,
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
