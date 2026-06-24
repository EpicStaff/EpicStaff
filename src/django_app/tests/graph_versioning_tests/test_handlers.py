from tables.graph_versioning.handlers import (
    CrewNodeHandler,
    SubgraphNodeHandler,
    CodeAgentNodeHandler,
    WebhookTriggerNodeHandler,
    TelegramTriggerNodeHandler,
    _MissingSets,
    HANDLER_REGISTRY,
)
from tables.import_export.enums import NodeType


# ---------------------------------------------------------------------------
# CrewNodeHandler — 3 existing tests (kept as-is, inline dicts)
# ---------------------------------------------------------------------------


def test_crew_handler_finds_missing_id(crew_node_dict, full_missing_sets):
    handler = CrewNodeHandler()

    missing_id = handler.find_missing_id(crew_node_dict, full_missing_sets)

    assert missing_id == crew_node_dict["crew"]


def test_crew_handler_returns_none_when_crew_exists(crew_node_dict, empty_missing_sets):
    handler = CrewNodeHandler()

    missing_id = handler.find_missing_id(crew_node_dict, empty_missing_sets)

    assert missing_id is None


def test_crew_handler_skips_node(crew_node_dict):
    handler = CrewNodeHandler()

    should_skip, warning = handler.handle(
        crew_node_dict, missing_id=crew_node_dict["crew"]
    )

    assert should_skip is True
    assert warning["type"] == "node_skipped"


def test_crew_handler_warning_contains_dependency_label(crew_node_dict):
    # Arrange
    handler = CrewNodeHandler()

    # Act
    _, warning = handler.handle(crew_node_dict, missing_id=crew_node_dict["crew"])

    # Assert
    assert "Project" in warning["reason"]


def test_crew_handler_warning_has_no_node_id_field(crew_node_dict):
    # SkipNodeHandler warnings must NOT include node_id
    handler = CrewNodeHandler()

    _, warning = handler.handle(crew_node_dict, missing_id=crew_node_dict["crew"])

    assert "node_id" not in warning


# ---------------------------------------------------------------------------
# SubgraphNodeHandler
# ---------------------------------------------------------------------------


def test_subgraph_handler_finds_missing_id(subgraph_node_dict, full_missing_sets):
    # Arrange
    handler = SubgraphNodeHandler()

    # Act
    missing_id = handler.find_missing_id(subgraph_node_dict, full_missing_sets)

    # Assert
    assert missing_id == subgraph_node_dict["subgraph"]


def test_subgraph_handler_returns_none_when_dep_available(
    subgraph_node_dict, empty_missing_sets
):
    # Arrange
    handler = SubgraphNodeHandler()

    # Act
    missing_id = handler.find_missing_id(subgraph_node_dict, empty_missing_sets)

    # Assert
    assert missing_id is None


def test_subgraph_handler_handle_returns_should_skip_false(subgraph_node_dict):
    # Arrange
    handler = SubgraphNodeHandler()

    # Act
    should_skip, _ = handler.handle(
        subgraph_node_dict, missing_id=subgraph_node_dict["subgraph"]
    )

    # Assert
    assert should_skip is False


def test_subgraph_handler_nulls_fk_in_node(subgraph_node_dict):
    # Arrange
    handler = SubgraphNodeHandler()

    # Act
    handler.handle(subgraph_node_dict, missing_id=subgraph_node_dict["subgraph"])

    # Assert: mutation happened in-place
    assert subgraph_node_dict["subgraph"] is None


def test_subgraph_handler_warning_fields(subgraph_node_dict):
    # Arrange
    handler = SubgraphNodeHandler()
    missing_id = subgraph_node_dict["subgraph"]

    # Act
    _, warning = handler.handle(subgraph_node_dict, missing_id=missing_id)

    # Assert
    assert warning["type"] == "fk_nulled"
    assert warning["node_id"] == subgraph_node_dict["id"]
    assert warning["field"] == "subgraph"
    assert warning["missing_id"] == missing_id
    assert "Subflow" in warning["reason"]


# ---------------------------------------------------------------------------
# CodeAgentNodeHandler
# ---------------------------------------------------------------------------


def test_code_agent_handler_finds_missing_id(code_agent_node_dict, full_missing_sets):
    # Arrange
    handler = CodeAgentNodeHandler()

    # Act
    missing_id = handler.find_missing_id(code_agent_node_dict, full_missing_sets)

    # Assert
    assert missing_id == code_agent_node_dict["llm_config"]


def test_code_agent_handler_returns_none_when_dep_available(
    code_agent_node_dict, empty_missing_sets
):
    # Arrange
    handler = CodeAgentNodeHandler()

    # Act
    missing_id = handler.find_missing_id(code_agent_node_dict, empty_missing_sets)

    # Assert
    assert missing_id is None


def test_code_agent_handler_handle_returns_should_skip_false(code_agent_node_dict):
    # Arrange
    handler = CodeAgentNodeHandler()

    # Act
    should_skip, _ = handler.handle(
        code_agent_node_dict, missing_id=code_agent_node_dict["llm_config"]
    )

    # Assert
    assert should_skip is False


def test_code_agent_handler_nulls_fk_in_node(code_agent_node_dict):
    # Arrange
    handler = CodeAgentNodeHandler()

    # Act
    handler.handle(code_agent_node_dict, missing_id=code_agent_node_dict["llm_config"])

    # Assert
    assert code_agent_node_dict["llm_config"] is None


def test_code_agent_handler_warning_fields(code_agent_node_dict):
    # Arrange
    handler = CodeAgentNodeHandler()
    missing_id = code_agent_node_dict["llm_config"]

    # Act
    _, warning = handler.handle(code_agent_node_dict, missing_id=missing_id)

    # Assert
    assert warning["type"] == "fk_nulled"
    assert warning["node_id"] == code_agent_node_dict["id"]
    assert warning["field"] == "llm_config"
    assert warning["missing_id"] == missing_id
    assert "LLMConfig" in warning["reason"]


# ---------------------------------------------------------------------------
# WebhookTriggerNodeHandler
# ---------------------------------------------------------------------------


def test_webhook_trigger_handler_finds_missing_id(
    webhook_trigger_node_dict, full_missing_sets
):
    # Arrange
    handler = WebhookTriggerNodeHandler()

    # Act
    missing_id = handler.find_missing_id(webhook_trigger_node_dict, full_missing_sets)

    # Assert
    assert missing_id == webhook_trigger_node_dict["webhook_trigger"]


def test_webhook_trigger_handler_returns_none_when_dep_available(
    webhook_trigger_node_dict, empty_missing_sets
):
    # Arrange
    handler = WebhookTriggerNodeHandler()

    # Act
    missing_id = handler.find_missing_id(webhook_trigger_node_dict, empty_missing_sets)

    # Assert
    assert missing_id is None


def test_webhook_trigger_handler_handle_returns_should_skip_false(
    webhook_trigger_node_dict,
):
    # Arrange
    handler = WebhookTriggerNodeHandler()

    # Act
    should_skip, _ = handler.handle(
        webhook_trigger_node_dict,
        missing_id=webhook_trigger_node_dict["webhook_trigger"],
    )

    # Assert
    assert should_skip is False


def test_webhook_trigger_handler_nulls_fk_in_node(webhook_trigger_node_dict):
    # Arrange
    handler = WebhookTriggerNodeHandler()

    # Act
    handler.handle(
        webhook_trigger_node_dict,
        missing_id=webhook_trigger_node_dict["webhook_trigger"],
    )

    # Assert
    assert webhook_trigger_node_dict["webhook_trigger"] is None


def test_webhook_trigger_handler_warning_fields(webhook_trigger_node_dict):
    # Arrange
    handler = WebhookTriggerNodeHandler()
    missing_id = webhook_trigger_node_dict["webhook_trigger"]

    # Act
    _, warning = handler.handle(webhook_trigger_node_dict, missing_id=missing_id)

    # Assert
    assert warning["type"] == "fk_nulled"
    assert warning["node_id"] == webhook_trigger_node_dict["id"]
    assert warning["field"] == "webhook_trigger"
    assert warning["missing_id"] == missing_id
    assert "Webhook Trigger" in warning["reason"]


# ---------------------------------------------------------------------------
# TelegramTriggerNodeHandler
# ---------------------------------------------------------------------------


def test_telegram_trigger_handler_finds_missing_id(
    telegram_trigger_node_dict, full_missing_sets
):
    # Arrange
    handler = TelegramTriggerNodeHandler()

    # Act
    missing_id = handler.find_missing_id(telegram_trigger_node_dict, full_missing_sets)

    # Assert
    assert missing_id == telegram_trigger_node_dict["webhook_trigger"]


def test_telegram_trigger_handler_returns_none_when_dep_available(
    telegram_trigger_node_dict, empty_missing_sets
):
    # Arrange
    handler = TelegramTriggerNodeHandler()

    # Act
    missing_id = handler.find_missing_id(telegram_trigger_node_dict, empty_missing_sets)

    # Assert
    assert missing_id is None


def test_telegram_trigger_handler_handle_returns_should_skip_false(
    telegram_trigger_node_dict,
):
    # Arrange
    handler = TelegramTriggerNodeHandler()

    # Act
    should_skip, _ = handler.handle(
        telegram_trigger_node_dict,
        missing_id=telegram_trigger_node_dict["webhook_trigger"],
    )

    # Assert
    assert should_skip is False


def test_telegram_trigger_handler_nulls_fk_in_node(telegram_trigger_node_dict):
    # Arrange
    handler = TelegramTriggerNodeHandler()

    # Act
    handler.handle(
        telegram_trigger_node_dict,
        missing_id=telegram_trigger_node_dict["webhook_trigger"],
    )

    # Assert
    assert telegram_trigger_node_dict["webhook_trigger"] is None


def test_telegram_trigger_handler_warning_fields(telegram_trigger_node_dict):
    # Arrange
    handler = TelegramTriggerNodeHandler()
    missing_id = telegram_trigger_node_dict["webhook_trigger"]

    # Act
    _, warning = handler.handle(telegram_trigger_node_dict, missing_id=missing_id)

    # Assert
    assert warning["type"] == "fk_nulled"
    assert warning["node_id"] == telegram_trigger_node_dict["id"]
    assert warning["field"] == "webhook_trigger"
    assert warning["missing_id"] == missing_id
    assert "Webhook Trigger" in warning["reason"]


# ---------------------------------------------------------------------------
# HANDLER_REGISTRY
# ---------------------------------------------------------------------------


def test_handler_registry_contains_all_five_node_types():
    expected_types = {
        NodeType.CREW_NODE,
        NodeType.SUBGRAPH_NODE,
        NodeType.CODE_AGENT_NODE,
        NodeType.WEBHOOK_TRIGGER_NODE,
        NodeType.TELEGRAM_TRIGGER_NODE,
    }

    assert set(HANDLER_REGISTRY.keys()) == expected_types


def test_handler_registry_crew_node_maps_to_crew_handler():
    assert isinstance(HANDLER_REGISTRY[NodeType.CREW_NODE], CrewNodeHandler)


def test_handler_registry_subgraph_node_maps_to_subgraph_handler():
    assert isinstance(HANDLER_REGISTRY[NodeType.SUBGRAPH_NODE], SubgraphNodeHandler)


def test_handler_registry_code_agent_node_maps_to_code_agent_handler():
    assert isinstance(HANDLER_REGISTRY[NodeType.CODE_AGENT_NODE], CodeAgentNodeHandler)


def test_handler_registry_webhook_trigger_node_maps_to_webhook_handler():
    assert isinstance(
        HANDLER_REGISTRY[NodeType.WEBHOOK_TRIGGER_NODE], WebhookTriggerNodeHandler
    )


def test_handler_registry_telegram_trigger_node_maps_to_telegram_handler():
    assert isinstance(
        HANDLER_REGISTRY[NodeType.TELEGRAM_TRIGGER_NODE], TelegramTriggerNodeHandler
    )
