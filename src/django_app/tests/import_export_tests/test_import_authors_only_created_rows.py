"""An import authors exactly the rows it inserts, and never a row it reuses or updates.

The authorship test walks the import registry: every top-level strategy whose model
records an author gets a case, so a new strategy fails here until it has a source
factory and stamps `created_by` on the rows it creates. Not walked here:

- graph node strategies: they only run as children of a flow import, covered by
  `test_node_authorship_import_export.py`, which builds one node of every type in
  `NODE_RELATIONS`;
- `Session`: its strategy is export-only (`create_entity` raises);
- tag strategies: tag models record no author.

Each case exports a source authored in `beta` and imports it into `acme`; org-scoped
reuse never reaches across orgs, so the import genuinely creates the rows in `acme`.
"""

from collections.abc import Callable

import pytest
from django.contrib.auth import get_user_model
from django.db.models import Model

from agents.models import AgentDefinition, Surface
from rbac.authorship.policy import has_author_field
from rbac.models import OrganizationUser
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.schemas import ImportSettings
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.import_service import ImportService
from tables.import_export.strategies.nodes.node_maps import NODE_TYPE_TO_ENTITY_TYPE
from tables.models import (
    EmbeddingConfig,
    EmbeddingModel,
    Graph,
    LLMConfig,
    LLMModel,
    RealtimeConfig,
    RealtimeModel,
    RealtimeTranscriptionConfig,
    RealtimeTranscriptionModel,
    StartNode,
    WebhookTrigger,
)
from tables.models.audit_filter_preset_models import AuditFilterPreset
from tables.models.label_models import Label
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool, PythonCodeToolConfig
from tables.models.realtime_models import (
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    OpenAIRealtimeConfig,
)
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

NODE_ENTITY_TYPES = frozenset(NODE_TYPE_TO_ENTITY_TYPE.values())
EXPORT_ONLY_ENTITY_TYPES = frozenset({EntityType.SESSION})

# Source factories take (org, author, provider) and return the row to export.
SourceFactory = Callable[..., Model]


def _llm_model(org, author, provider):
    return LLMModel.objects.create(
        name="imported-llm", llm_provider=provider, is_custom=True, org=org, created_by=author
    )


def _embedding_model(org, author, provider):
    return EmbeddingModel.objects.create(
        name="imported-embedder",
        embedding_provider=provider,
        is_custom=True,
        org=org,
        created_by=author,
    )


def _realtime_model(org, author, provider):
    return RealtimeModel.objects.create(
        name="imported-realtime", provider=provider, is_custom=True, org=org, created_by=author
    )


def _realtime_transcription_model(org, author, provider):
    return RealtimeTranscriptionModel.objects.create(
        name="imported-transcription",
        provider=provider,
        is_custom=True,
        org=org,
        created_by=author,
    )


def _llm_config(org, author, provider):
    return LLMConfig.objects.create(
        custom_name="imported-llm-config",
        model=_llm_model(org, author, provider),
        org=org,
        created_by=author,
    )


def _embedding_config(org, author, provider):
    return EmbeddingConfig.objects.create(
        custom_name="imported-embedding-config",
        model=_embedding_model(org, author, provider),
        org=org,
        created_by=author,
    )


def _realtime_config(org, author, provider):
    return RealtimeConfig.objects.create(
        custom_name="imported-realtime-config",
        realtime_model=_realtime_model(org, author, provider),
        org=org,
        created_by=author,
    )


def _realtime_transcription_config(org, author, provider):
    return RealtimeTranscriptionConfig.objects.create(
        custom_name="imported-transcription-config",
        realtime_transcription_model=_realtime_transcription_model(org, author, provider),
        org=org,
        created_by=author,
    )


def _openai_realtime_config(org, author, provider):
    return OpenAIRealtimeConfig.objects.create(
        custom_name="imported-openai-realtime",
        model_name="gpt-realtime-1.5",
        org=org,
        created_by=author,
    )


def _elevenlabs_realtime_config(org, author, provider):
    return ElevenLabsRealtimeConfig.objects.create(
        custom_name="imported-elevenlabs", org=org, created_by=author
    )


def _gemini_realtime_config(org, author, provider):
    return GeminiRealtimeConfig.objects.create(
        custom_name="imported-gemini", org=org, created_by=author
    )


def _python_code_tool(org, author, provider):
    python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    tool = PythonCodeTool.objects.create(
        name="imported-python-tool",
        description="tool",
        python_code=python_code,
        org=org,
        created_by=author,
    )
    PythonCodeToolConfig.objects.create(
        name="imported-tool-config", tool=tool, configuration={}, org=org, created_by=author
    )
    return tool


def _mcp_tool(org, author, provider):
    return McpTool.objects.create(
        name="imported-mcp-tool",
        transport="http://mcp.example.com/sse",
        tool_name="search",
        org=org,
        created_by=author,
    )


def _webhook_trigger(org, author, provider):
    return WebhookTrigger.objects.create(path="imported-hook", org=org, created_by=author)


def _flow(org, author, provider):
    graph = Graph.objects.create(
        name="imported-flow", org=org, metadata={"nodes": [], "edges": []}, created_by=author
    )
    StartNode.objects.create(graph=graph, variables={}, created_by=author)
    return graph


def _label(org, author, provider):
    return Label.objects.create(
        name="imported-label", org=org, scope=Label.Scope.FLOW, created_by=author
    )


def _agent_definition(org, author, provider):
    return AgentDefinition.objects.create(
        org=org,
        name="imported-agent-definition",
        description="description",
        instruction_list=[{"name": "Instruction_1.md", "content": "instructions"}],
        created_by=author,
    )


def _audit_filter_preset(org, author, provider):
    return AuditFilterPreset.objects.create(
        org=org, created_by=author, name="imported-audit-filter-preset", filter_body={}
    )


def _surface(org, author, provider):
    return Surface.objects.create(
        org=org, name="imported-surface", instructions="instructions", created_by=author
    )


SOURCE_FACTORIES: dict[EntityType, SourceFactory] = {
    EntityType.LLM_MODEL: _llm_model,
    EntityType.EMBEDDING_MODEL: _embedding_model,
    EntityType.REALTIME_MODEL: _realtime_model,
    EntityType.REALTIME_TRANSCRIPTION_MODEL: _realtime_transcription_model,
    EntityType.LLM_CONFIG: _llm_config,
    EntityType.EMBEDDING_CONFIG: _embedding_config,
    EntityType.REALTIME_CONFIG: _realtime_config,
    EntityType.REALTIME_TRANSCRIPTION_CONFIG: _realtime_transcription_config,
    EntityType.OPENAI_REALTIME_CONFIG: _openai_realtime_config,
    EntityType.ELEVENLABS_REALTIME_CONFIG: _elevenlabs_realtime_config,
    EntityType.GEMINI_REALTIME_CONFIG: _gemini_realtime_config,
    EntityType.PYTHON_CODE_TOOL: _python_code_tool,
    EntityType.MCP_TOOL: _mcp_tool,
    EntityType.WEBHOOK_TRIGGER: _webhook_trigger,
    EntityType.GRAPH: _flow,
    EntityType.LABEL: _label,
    EntityType.AGENT_DEFINITION: _agent_definition,
    EntityType.SURFACE: _surface,
    EntityType.AUDIT_FILTER_PRESET: _audit_filter_preset,
}


def _strategy_model(entity_type: EntityType) -> type[Model] | None:
    serializer_class = getattr(entity_registry.get_strategy(entity_type), "serializer_class", None)
    return getattr(getattr(serializer_class, "Meta", None), "model", None)


def _authored_top_level_entity_types() -> list[EntityType]:
    """Every registered top-level strategy whose model records an author.

    A strategy without a resolvable model is listed too, so its case fails loudly
    instead of being skipped.
    """
    return [
        entity_type
        for entity_type in EntityType
        if entity_registry.has_strategy(entity_type)
        and entity_type not in NODE_ENTITY_TYPES
        and entity_type not in EXPORT_ONLY_ENTITY_TYPES
        and (
            _strategy_model(entity_type) is None
            or has_author_field(_strategy_model(entity_type))
        )
    ]


@pytest.fixture
def beta_author(beta, role_member):
    user = get_user_model().objects.create_user(
        email="beta-source-author@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=beta, role=role_member)
    return user


def _import(export_data, entity_type, org, user):
    ImportService(entity_registry).import_data(
        export_data,
        main_entity=entity_type,
        settings=ImportSettings(import_labels=True),
        org_id=org.id,
        user=user,
    )


def _export(entity_type, source):
    return ExportService(entity_registry).export_entities(entity_type, [source.id])


def test_authored_strategies_have_source_factories():
    assert set(_authored_top_level_entity_types()) == set(SOURCE_FACTORIES)


@pytest.mark.django_db
@pytest.mark.parametrize("entity_type", _authored_top_level_entity_types(), ids=str)
def test_fresh_import_authors_the_created_rows_with_the_importing_user(
    entity_type,
    acme,
    beta,
    admin_acme,
    beta_author,
    openai_provider,
    openai_realtime_builtin_model,
):
    model = _strategy_model(entity_type)
    assert model is not None, f"{entity_type}: strategy has no serializer_class.Meta.model"
    assert entity_type in SOURCE_FACTORIES, (
        f"{entity_type}: add a source factory to SOURCE_FACTORIES so its import authorship "
        "is tested"
    )
    source = SOURCE_FACTORIES[entity_type](beta, beta_author, openai_provider)

    _import(_export(entity_type, source), entity_type, acme, admin_acme)

    imported_authors = set(model.objects.filter(org=acme).values_list("created_by_id", flat=True))
    assert imported_authors == {admin_acme.id}
    assert model.objects.get(pk=source.pk).created_by_id == beta_author.id


@pytest.mark.django_db
def test_import_authors_python_tool_configs_with_the_importing_user(
    acme, beta, admin_acme, beta_author, openai_provider
):
    source = _python_code_tool(beta, beta_author, openai_provider)
    export_data = _export(EntityType.PYTHON_CODE_TOOL, source)

    _import(export_data, EntityType.PYTHON_CODE_TOOL, acme, admin_acme)

    imported_configs = PythonCodeToolConfig.objects.filter(org=acme)
    assert list(imported_configs.values_list("name", flat=True)) == ["imported-tool-config"]
    assert set(imported_configs.values_list("created_by_id", flat=True)) == {admin_acme.id}


@pytest.mark.django_db
def test_import_reusing_an_unauthored_label_leaves_it_unauthored(acme, beta, admin_acme):
    existing = Label.objects.create(name="shared-label", org=acme, scope=Label.Scope.FLOW)
    source = Label.objects.create(name="shared-label", org=beta, scope=Label.Scope.FLOW)

    _import(_export(EntityType.LABEL, source), EntityType.LABEL, acme, admin_acme)

    assert list(Label.objects.filter(org=acme).values_list("pk", flat=True)) == [existing.pk]
    existing.refresh_from_db()
    assert existing.created_by_id is None
