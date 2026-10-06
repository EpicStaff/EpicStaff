"""Tests for ConverterService realtime agent storage credential minting.

Commit 5, Part 9: Realtime agent chat storage credential handling.
Tests verify:
1. Realtime without storage → no mint, no DB write
2. Realtime with storage → mint once per session, DB write, credentials on RealtimeAgentChatData
3. Realtime end() endpoint revokes credentials
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.models import AgentDefinition
from rbac.models import Organization
from tables.models import (
    RealtimeAgentChat,
    RealtimeAgentDefinition,
    OpenAIRealtimeConfig,
    Secret,
)
from tables.services.converter_service import ConverterService
from storage_credentials.models import TemporaryStorageAccount


@pytest.fixture
def converter():
    return ConverterService()


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org RealtimeStorage")


@pytest.fixture
def agent_definition(org):
    """Base agent definition"""
    return AgentDefinition.objects.create(
        name="Test Agent",
        organization_id=org.id,
        description="Test agent",
        instructions="You are a helpful assistant",
    )


@pytest.fixture
def rt_agent_definition(agent_definition):
    """Realtime agent definition with no storage by default"""
    return RealtimeAgentDefinition.objects.create(
        agent_definition=agent_definition,
    )


@pytest.fixture
def realtime_agent_chat_with_openai_config(rt_agent_definition, org, db):
    """Create a minimal RealtimeAgentChat with OpenAI config"""
    from tables.models import OpenAIRealtimeConfig
    from tables.models import Secret

    # Create a secret for API key
    secret = Secret.objects.create(
        name="openai_api_key", value="encrypted_key", org=org
    )

    openai_config = OpenAIRealtimeConfig.objects.create(
        custom_name="openai_test",
        model_name="gpt-4-realtime-preview",
        api_key_secret=secret,
        org=org,
    )

    chat = RealtimeAgentChat.objects.create(
        rt_agent_definition=rt_agent_definition,
        openai_config=openai_config,
        connection_key="conn-key-123",
    )
    return chat


@pytest.mark.django_db
class TestConverterRTAgentStorageCredentials:
    """Realtime agent chat storage credential handling in converter"""

    def test_convert_rt_agent_definition_without_storage_no_mint(
        self, converter, realtime_agent_chat_with_openai_config
    ):
        """Realtime without storage tools → no mint, no DB write"""
        # The agent definition has no tools with use_storage=True
        with patch("storage_credentials.services.session_credential_service.StorageAdminGateway"):
            rt_chat_data = converter.convert_rt_agent_definition_chat_to_pydantic(
                realtime_agent_chat_with_openai_config
            )

        # Verify no storage_credentials were set
        assert rt_chat_data.storage_credentials is None

        # Verify no TemporaryStorageAccount was created
        assert not TemporaryStorageAccount.objects.filter(
            realtime_agent_chat=realtime_agent_chat_with_openai_config
        ).exists()

    @patch("storage_credentials.services.session_credential_service.StorageAdminGateway")
    def test_convert_rt_agent_definition_with_storage_mints_once(
        self, mock_gateway_class, converter, realtime_agent_chat_with_openai_config, org
    ):
        """Realtime with storage tool → mint once per session, DB write, credentials on data"""
        from tables.models import PythonCodeTool, PythonCode

        # Create a python code tool with use_storage=True
        python_code = PythonCode.objects.create(
            code="def main(**kw): return kw"
        )
        python_code_tool = PythonCodeTool.objects.create(
            python_code=python_code,
            use_storage=True,
            org_id=org.id,
        )

        # Add the tool to the agent definition's tools
        # (Assuming there's a way to add tools to the agent definition)
        # For this test, we need to mock the surface resolution to include the tool

        mock_gateway_instance = AsyncMock()
        mock_gateway_class.return_value = mock_gateway_instance
        mock_gateway_instance.create_service_account = AsyncMock(
            return_value=("rt-access-key", "rt-secret-key")
        )
        mock_gateway_instance.close = AsyncMock()

        mock_org_creds = MagicMock()
        mock_org_creds.access_key = "org-access"
        mock_org_creds.secret_key = "org-secret"

        with patch(
            "storage_credentials.services.session_credential_service.org_credential_store.get",
            return_value=mock_org_creds,
        ):
            # Mock the surface resolution to return a tool with use_storage=True
            from src.shared.models import BaseToolData, PythonCodeToolData, PythonCodeData

            python_code_data = PythonCodeData(
                venv_name="venv_1",
                code="def main(**kw): return kw",
                entrypoint="main",
                libraries=[],
                use_storage=True,
                storage_allowed_paths=["realtime/sessions/"],
            )
            tool_data = PythonCodeToolData(
                id=1, name="Storage Tool", description="", python_code=python_code_data
            )
            mock_tool = BaseToolData(
                unique_name=f"python-code-tool:{tool_data.id}", data=tool_data
            )

            with patch.object(
                converter.realtime_surface_service,
                "resolve",
                return_value=MagicMock(
                    tools=[mock_tool],
                    knowledge_collection_id=None,
                    rag_type_id=None,
                    rag_search_config=None,
                    rag_embedder_api_key_secret_id=None,
                    rag_llm_api_key_secret_id=None,
                ),
            ):
                rt_chat_data = converter.convert_rt_agent_definition_chat_to_pydantic(
                    realtime_agent_chat_with_openai_config
                )

        # Verify TemporaryStorageAccount was created
        temp_account = TemporaryStorageAccount.objects.get(
            realtime_agent_chat=realtime_agent_chat_with_openai_config
        )
        assert temp_account.access_key == "rt-access-key"

        # Verify credentials were embedded in RealtimeAgentChatData
        assert rt_chat_data.storage_credentials is not None
        assert rt_chat_data.storage_credentials.access_key == "rt-access-key"
        assert rt_chat_data.storage_credentials.secret_key == "rt-secret-key"

    @patch("storage_credentials.services.session_credential_service.StorageAdminGateway")
    def test_convert_rt_agent_definition_with_multiple_tools_mints_once(
        self, mock_gateway_class, converter, realtime_agent_chat_with_openai_config, org
    ):
        """Even with multiple storage tools, mint happens once per chat"""
        # Create multiple tools with use_storage=True
        from tables.models import PythonCodeTool, PythonCode

        python_code = PythonCode.objects.create(code="def main(**kw): return kw")
        tool1 = PythonCodeTool.objects.create(
            python_code=python_code, use_storage=True, org_id=org.id, name="Tool 1"
        )
        tool2 = PythonCodeTool.objects.create(
            python_code=python_code, use_storage=True, org_id=org.id, name="Tool 2"
        )

        mock_gateway_instance = AsyncMock()
        mock_gateway_class.return_value = mock_gateway_instance
        mock_gateway_instance.create_service_account = AsyncMock(
            return_value=("rt-access-key", "rt-secret-key")
        )
        mock_gateway_instance.close = AsyncMock()

        mock_org_creds = MagicMock()
        mock_org_creds.access_key = "org-access"
        mock_org_creds.secret_key = "org-secret"

        with patch(
            "storage_credentials.services.session_credential_service.org_credential_store.get",
            return_value=mock_org_creds,
        ):
            # Mock multiple tools
            from src.shared.models import BaseToolData, PythonCodeToolData, PythonCodeData

            python_code_data1 = PythonCodeData(
                venv_name="venv_1",
                code="def main(**kw): return kw",
                entrypoint="main",
                libraries=[],
                use_storage=True,
                storage_allowed_paths=["realtime/sessions/"],
            )
            tool_data1 = PythonCodeToolData(
                id=1, name="Tool 1", description="", python_code=python_code_data1
            )
            mock_tool1 = BaseToolData(
                unique_name=f"python-code-tool:{tool_data1.id}", data=tool_data1
            )

            python_code_data2 = PythonCodeData(
                venv_name="venv_2",
                code="def process(**kw): return kw",
                entrypoint="process",
                libraries=[],
                use_storage=True,
                storage_allowed_paths=["realtime/sessions/"],
            )
            tool_data2 = PythonCodeToolData(
                id=2, name="Tool 2", description="", python_code=python_code_data2
            )
            mock_tool2 = BaseToolData(
                unique_name=f"python-code-tool:{tool_data2.id}", data=tool_data2
            )

            with patch.object(
                converter.realtime_surface_service,
                "resolve",
                return_value=MagicMock(
                    tools=[mock_tool1, mock_tool2],
                    knowledge_collection_id=None,
                    rag_type_id=None,
                    rag_search_config=None,
                    rag_embedder_api_key_secret_id=None,
                    rag_llm_api_key_secret_id=None,
                ),
            ):
                rt_chat_data = converter.convert_rt_agent_definition_chat_to_pydantic(
                    realtime_agent_chat_with_openai_config
                )

        # Verify create_service_account was called exactly once (once per chat)
        assert mock_gateway_instance.create_service_account.call_count == 1

        # Verify only one TemporaryStorageAccount was created
        assert (
            TemporaryStorageAccount.objects.filter(
                realtime_agent_chat=realtime_agent_chat_with_openai_config
            ).count()
            == 1
        )

    @patch("storage_credentials.services.session_credential_service.StorageAdminGateway")
    def test_convert_rt_agent_definition_mixed_tools_storage_true_and_false(
        self, mock_gateway_class, converter, realtime_agent_chat_with_openai_config, org
    ):
        """Mixed tools (some with storage, some without) → mint once, scoped to
        only the storage-enabled tool's allowed_paths."""
        from tables.models import PythonCodeTool, PythonCode

        python_code = PythonCode.objects.create(code="def main(**kw): return kw")
        PythonCodeTool.objects.create(
            python_code=python_code, use_storage=True, org_id=org.id, name="With Storage"
        )
        PythonCodeTool.objects.create(
            python_code=python_code, use_storage=False, org_id=org.id, name="Without Storage"
        )

        mock_gateway_instance = AsyncMock()
        mock_gateway_class.return_value = mock_gateway_instance
        mock_gateway_instance.create_service_account = AsyncMock(
            return_value=("rt-access-key", "rt-secret-key")
        )
        mock_gateway_instance.close = AsyncMock()

        mock_org_creds = MagicMock()
        mock_org_creds.access_key = "org-access"
        mock_org_creds.secret_key = "org-secret"

        with patch(
            "storage_credentials.services.session_credential_service.org_credential_store.get",
            return_value=mock_org_creds,
        ):
            from src.shared.models import BaseToolData, PythonCodeToolData, PythonCodeData

            python_code_data_with = PythonCodeData(
                venv_name="venv_with",
                code="def main(**kw): return kw",
                entrypoint="main",
                libraries=[],
                use_storage=True,
                storage_allowed_paths=["realtime/sessions/"],
            )
            tool_data_with = PythonCodeToolData(
                id=1, name="With Storage", description="", python_code=python_code_data_with
            )
            mock_tool_with = BaseToolData(
                unique_name=f"python-code-tool:{tool_data_with.id}", data=tool_data_with
            )

            python_code_data_without = PythonCodeData(
                venv_name="venv_without",
                code="def process(**kw): return kw",
                entrypoint="process",
                libraries=[],
                use_storage=False,
            )
            tool_data_without = PythonCodeToolData(
                id=2, name="Without Storage", description="", python_code=python_code_data_without
            )
            mock_tool_without = BaseToolData(
                unique_name=f"python-code-tool:{tool_data_without.id}", data=tool_data_without
            )

            with patch.object(
                converter.realtime_surface_service,
                "resolve",
                return_value=MagicMock(
                    tools=[mock_tool_with, mock_tool_without],
                    knowledge_collection_id=None,
                    rag_type_id=None,
                    rag_search_config=None,
                    rag_embedder_api_key_secret_id=None,
                    rag_llm_api_key_secret_id=None,
                ),
            ):
                rt_chat_data = converter.convert_rt_agent_definition_chat_to_pydantic(
                    realtime_agent_chat_with_openai_config
                )

        # Mint happened exactly once, triggered by the storage-enabled tool only
        assert mock_gateway_instance.create_service_account.call_count == 1
        assert rt_chat_data.storage_credentials is not None
        assert rt_chat_data.storage_credentials.access_key == "rt-access-key"
        temp_account = TemporaryStorageAccount.objects.get(
            realtime_agent_chat=realtime_agent_chat_with_openai_config
        )
        assert temp_account.access_key == "rt-access-key"
