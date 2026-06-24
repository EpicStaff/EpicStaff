import pytest

from tables.graph_versioning.handlers import _MissingSets
from tables.import_export.enums import NodeType
from tables.models import Organization
from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME

# Dependency IDs used consistently across all handler tests
_CREW_ID = 42
_LLM_CONFIG_ID = 3
_SUBGRAPH_ID = 5
_WEBHOOK_TRIGGER_ID = 7


@pytest.fixture
def default_org(db):
    """Create the default Organization required by create_graph_from_snapshot."""
    return Organization.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)[0]


@pytest.fixture
def crew_node_dict():
    return {
        "id": 10,
        "node_type": NodeType.CREW_NODE,
        "node_name": "Crew Node",
        "crew": _CREW_ID,
    }


@pytest.fixture
def subgraph_node_dict():
    return {
        "id": 30,
        "node_type": NodeType.SUBGRAPH_NODE,
        "node_name": "Subgraph Node",
        "subgraph": _SUBGRAPH_ID,
    }


@pytest.fixture
def code_agent_node_dict():
    return {
        "id": 40,
        "node_type": NodeType.CODE_AGENT_NODE,
        "node_name": "Code Agent Node",
        "llm_config": _LLM_CONFIG_ID,
    }


@pytest.fixture
def webhook_trigger_node_dict():
    return {
        "id": 50,
        "node_type": NodeType.WEBHOOK_TRIGGER_NODE,
        "node_name": "Webhook Trigger Node",
        "webhook_trigger": _WEBHOOK_TRIGGER_ID,
    }


@pytest.fixture
def telegram_trigger_node_dict():
    return {
        "id": 60,
        "node_type": NodeType.TELEGRAM_TRIGGER_NODE,
        "node_name": "Telegram Trigger Node",
        "webhook_trigger": _WEBHOOK_TRIGGER_ID,
    }


@pytest.fixture
def empty_missing_sets():
    return _MissingSets(crews=set(), subgraphs=set(), llm_configs=set(), webhooks=set())


@pytest.fixture
def full_missing_sets():
    return _MissingSets(
        crews={_CREW_ID},
        subgraphs={_SUBGRAPH_ID},
        llm_configs={_LLM_CONFIG_ID},
        webhooks={_WEBHOOK_TRIGGER_ID},
    )


@pytest.fixture
def manager():
    from tables.graph_versioning.manager import GraphVersioningManager

    return GraphVersioningManager()


@pytest.fixture
def service():
    from tables.graph_versioning.services import GraphVersioningService

    return GraphVersioningService()


@pytest.fixture
def start_node_dict():
    from tables.import_export.enums import NodeType

    return {
        "id": 100,
        "node_type": NodeType.START_NODE,
        "node_name": "start",
    }


@pytest.fixture
def make_decision_table_node():
    from tables.import_export.enums import NodeType

    def _make(node_id=200, default_next=None, next_error=None, condition_groups=None):
        return {
            "id": node_id,
            "node_type": NodeType.DECISION_TABLE_NODE,
            "node_name": "DT Node",
            "default_next_node_id": default_next,
            "next_error_node_id": next_error,
            "condition_groups": condition_groups or [],
        }

    return _make
