"""
Copying a TelegramTriggerNode/McpTool must propagate the `_secret` FK, not
the raw field it replaced (found while wiring the FK in sensitive-field
subtask 3 — these two copy services still referenced the deleted fields).
"""

import pytest

from tables.models import Secret
from tables.models.graph_models import Graph, TelegramTriggerNode
from tables.models.mcp_models import McpTool
from tables.models.rbac_models import Organization
from tables.services.copy_services.mcp_tool_copy_service import McpToolCopyService
from tables.services.copy_services.node_copy_handlers import copy_telegram_trigger_node
from tables.services.secrets import secret_encryption


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org CopyServices")


@pytest.fixture
def secret(org):
    s = Secret(org=org, name="copy-service-test-key")
    secret_encryption.encrypt(text="sk-copy-me").write_to(s)
    s.save()
    return s


@pytest.mark.django_db
def test_copy_telegram_trigger_node_propagates_secret_fk(org, secret):
    graph = Graph.objects.create(name="source-graph", org=org)
    node = TelegramTriggerNode.objects.create(
        graph=graph, node_name="original", telegram_bot_api_key_secret=secret
    )

    other_graph = Graph.objects.create(name="target-graph", org=org)
    copied = copy_telegram_trigger_node(other_graph, node)

    assert copied.id != node.id
    assert copied.telegram_bot_api_key_secret_id == secret.id
    assert (
        secret_encryption.decrypt(
            encryptedtext=copied.telegram_bot_api_key_secret.value
        )
        == "sk-copy-me"
    )


@pytest.mark.django_db
def test_copy_mcp_tool_propagates_secret_fk(org, secret):
    tool = McpTool.objects.create(
        org=org,
        name="original-tool",
        transport="https://example.com/sse",
        tool_name="search",
        auth_secret=secret,
    )

    copied = McpToolCopyService().copy(tool)

    assert copied.id != tool.id
    assert copied.auth_secret_id == secret.id
    assert (
        secret_encryption.decrypt(encryptedtext=copied.auth_secret.value)
        == "sk-copy-me"
    )
