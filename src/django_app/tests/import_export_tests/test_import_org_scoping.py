import pytest

from tables.models import (
    Graph,
    LLMConfig,
    McpTool,
    PythonCode,
    PythonCodeTool,
    WebhookTrigger,
    WebhookTriggerNode,
)
from agents.models import AgentDefinition
from tables.models.label_models import Label
from tables.models.rbac_models import Organization
from tables.models.realtime_models import OpenAIRealtimeConfig
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.services.import_service import ImportService
from tables.import_export.schemas import ImportSettings


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B import target")


def _import(export_data, org_id):
    return ImportService(entity_registry).import_data(
        export_data,
        export_data["main_entity"],
        settings=ImportSettings(),
        org_id=org_id,
    )


@pytest.mark.django_db
class TestStrictCrossOrg:
    def test_agent_definition_not_reused_across_orgs(
        self, exportable_agent_definition, export_service, org_b
    ):
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [exportable_agent_definition.id]
        )

        id_mapper, _ = _import(export_data, org_b.id)

        # The definition and its LLMConfig must be CREATED in org_b, not reused
        # from default_org.
        assert id_mapper.get_reused_ids(EntityType.AGENT_DEFINITION) == []
        new_definition = AgentDefinition.objects.get(
            id=id_mapper.get_created_ids(EntityType.AGENT_DEFINITION)[0]
        )
        assert new_definition.organization_id == org_b.id

        new_cfg_ids = id_mapper.get_created_ids(EntityType.LLM_CONFIG)
        assert new_cfg_ids, "LLM config should be created in org_b, not reused"
        assert LLMConfig.objects.get(id=new_cfg_ids[0]).org_id == org_b.id

    def test_config_reused_within_same_org(
        self, exportable_agent_definition, export_service, default_org
    ):
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [exportable_agent_definition.id]
        )

        id_mapper, _ = _import(export_data, default_org.id)

        # Same org: the existing LLMConfig is reused, not duplicated
        assert id_mapper.get_reused_ids(
            EntityType.LLM_CONFIG
        ), "should reuse in same org"


@pytest.mark.django_db
class TestMcpAndLabelCrossOrg:
    def test_mcp_find_existing_is_org_scoped(self, default_org, org_b):
        mcp = McpTool.objects.create(
            name="shared-mcp", transport="http://x", tool_name="t", org=default_org
        )
        strategy = entity_registry.get_strategy(EntityType.MCP_TOOL)
        data = {"name": "shared-mcp", "transport": "http://x", "tool_name": "t"}

        assert strategy.find_existing(data, None, org_id=org_b.id) is None
        assert strategy.find_existing(data, None, org_id=default_org.id) == mcp

    def test_mcp_created_in_active_org(self, default_org, org_b):
        mcp = McpTool.objects.create(
            name="shared-mcp", transport="http://x", tool_name="t", org=default_org
        )
        strategy = entity_registry.get_strategy(EntityType.MCP_TOOL)
        export_data = {
            "main_entity": EntityType.MCP_TOOL,
            EntityType.MCP_TOOL: [strategy.export_entity(mcp)],
        }

        id_mapper, _ = _import(export_data, org_b.id)

        created = id_mapper.get_created_ids(EntityType.MCP_TOOL)
        assert created, "mcp tool must be created in org_b"
        assert McpTool.objects.get(id=created[0]).org_id == org_b.id

    def test_label_find_existing_is_org_scoped(self, default_org, org_b):
        label = Label.objects.create(name="Shared Label", org=default_org)
        strategy = entity_registry.get_strategy(EntityType.LABEL)
        data = {"name": "Shared Label", "parent": None}

        assert strategy.find_existing(data, None, org_id=org_b.id) is None
        assert strategy.find_existing(data, None, org_id=default_org.id) == label

    def test_label_created_in_active_org(self, default_org, org_b):
        label = Label.objects.create(name="Shared Label", org=default_org)
        export_data = {
            "main_entity": EntityType.GRAPH,
            EntityType.LABEL: [
                {"id": label.id, "name": label.name, "parent": None, "metadata": {}}
            ],
            EntityType.GRAPH: [],
        }
        id_mapper, _ = ImportService(entity_registry).import_data(
            export_data,
            EntityType.GRAPH,
            settings=ImportSettings(import_labels=True),
            org_id=org_b.id,
        )
        created = id_mapper.get_created_ids(EntityType.LABEL)
        assert created, "label must be created in org_b"
        assert Label.objects.get(id=created[0]).org_id == org_b.id

    def test_tool_scope_label_not_attached_to_imported_graph(
        self, export_service, default_org
    ):
        graph = Graph.objects.create(name="label-scope-graph", org=default_org)
        flow_label = Label.objects.create(
            name="flow-label", org=default_org, scope=Label.Scope.FLOW
        )
        tool_label = Label.objects.create(
            name="tool-label", org=default_org, scope=Label.Scope.TOOL
        )
        graph.labels.add(flow_label, tool_label)

        export_data = export_service.export_entities(EntityType.GRAPH, [graph.id])

        id_mapper, _ = ImportService(entity_registry).import_data(
            export_data,
            EntityType.GRAPH,
            settings=ImportSettings(import_labels=True),
            org_id=default_org.id,
        )

        new_graph = Graph.objects.get(id=id_mapper.get_created_ids(EntityType.GRAPH)[0])
        new_graph_label_names = set(new_graph.labels.values_list("name", flat=True))
        assert "flow-label" in new_graph_label_names
        assert "tool-label" not in new_graph_label_names


@pytest.mark.django_db
class TestHybridCrossOrg:
    def test_builtin_model_reused_custom_tool_created(
        self, exportable_agent_definition, export_service, org_b
    ):
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [exportable_agent_definition.id]
        )

        id_mapper, _ = _import(export_data, org_b.id)

        # Built-in model (is_custom=False) is shared across orgs -> reused
        assert id_mapper.get_reused_ids(
            EntityType.LLM_MODEL
        ), "built-in model should be reused across orgs"

        # Custom python tool is org-owned -> created in org_b, not reused
        created_tools = id_mapper.get_created_ids(EntityType.PYTHON_CODE_TOOL)
        assert created_tools, "custom tool must be created in org_b"
        new_tool = PythonCodeTool.objects.get(id=created_tools[0])
        assert new_tool.org_id == org_b.id
        assert new_tool.built_in is False


@pytest.mark.django_db
class TestProviderRealtimeConfigCrossOrg:
    """OpenAIRealtimeConfig (and its Eleven/Gemini
    siblings, same base strategy) now own `org` NOT NULL — create_entity must
    stamp it, and find_existing/uniqueness must not leak across orgs."""

    def test_create_entity_stamps_active_org(self, default_org):
        strategy = entity_registry.get_strategy(EntityType.OPENAI_REALTIME_CONFIG)
        data = {"custom_name": "openai-cfg", "model_name": "gpt-realtime-1.5"}

        created = strategy.create_entity(data, None, org_id=default_org.id)

        assert created.org_id == default_org.id

    def test_find_existing_is_org_scoped(self, default_org, org_b):
        cfg = OpenAIRealtimeConfig.objects.create(
            org=default_org, custom_name="shared-cfg", model_name="gpt-realtime-1.5"
        )
        strategy = entity_registry.get_strategy(EntityType.OPENAI_REALTIME_CONFIG)
        data = {"custom_name": "shared-cfg", "model_name": "gpt-realtime-1.5"}

        assert strategy.find_existing(data, None, org_id=org_b.id) is None
        assert strategy.find_existing(data, None, org_id=default_org.id) == cfg

    def test_created_in_active_org_not_reused_cross_org(self, default_org, org_b):
        OpenAIRealtimeConfig.objects.create(
            org=default_org, custom_name="shared-cfg", model_name="gpt-realtime-1.5"
        )
        existing = OpenAIRealtimeConfig.objects.get(custom_name="shared-cfg")
        strategy = entity_registry.get_strategy(EntityType.OPENAI_REALTIME_CONFIG)
        export_data = {
            "main_entity": EntityType.OPENAI_REALTIME_CONFIG,
            EntityType.OPENAI_REALTIME_CONFIG: [strategy.export_entity(existing)],
        }

        id_mapper, _ = _import(export_data, org_b.id)

        created = id_mapper.get_created_ids(EntityType.OPENAI_REALTIME_CONFIG)
        assert created, "config must be created in org_b, not reused from default_org"
        assert OpenAIRealtimeConfig.objects.get(id=created[0]).org_id == org_b.id

    def test_unique_name_check_is_org_scoped(self, default_org):
        OpenAIRealtimeConfig.objects.create(
            org=default_org, custom_name="dup-cfg", model_name="gpt-realtime-1.5"
        )
        strategy = entity_registry.get_strategy(EntityType.OPENAI_REALTIME_CONFIG)
        data = {"custom_name": "dup-cfg", "model_name": "gpt-realtime-1.5"}

        created = strategy.create_entity(data, None, org_id=default_org.id)

        # Same-org duplicate name must be disambiguated, not collide.
        assert created.custom_name != "dup-cfg"


@pytest.mark.django_db
class TestWebhookAndGraphCrossOrg:
    def test_webhook_find_existing_is_org_scoped(self, default_org, org_b):
        wt = WebhookTrigger.objects.create(path="shared-path", org=default_org)
        graph = Graph.objects.create(name="src flow", org=default_org)
        code = PythonCode.objects.create(
            code="def main(): ...", entrypoint="main", libraries=""
        )
        WebhookTriggerNode.objects.create(
            graph=graph, node_name="wt", webhook_trigger=wt, python_code=code
        )

        strategy = entity_registry.get_strategy(EntityType.WEBHOOK_TRIGGER)
        data = {"path": "shared-path"}

        # Only the org whose flow references the webhook can reuse it
        assert strategy.find_existing(data, None, org_id=org_b.id) is None
        assert strategy.find_existing(data, None, org_id=default_org.id) == wt

    def test_graph_imported_into_active_org_keeps_name(
        self, rich_seeded_db, export_service, org_b
    ):
        graph = rich_seeded_db["graph"]  # "graph1" in default_org
        export_data = export_service.export_entities(EntityType.GRAPH, [graph.id])

        id_mapper, _ = _import(export_data, org_b.id)

        new_graph = Graph.objects.get(id=id_mapper.get_created_ids(EntityType.GRAPH)[0])
        assert new_graph.org_id == org_b.id
        # name not suffixed: "graph1" doesn't exist in org_b (naming is org-scoped)
        assert new_graph.name == "graph1"
