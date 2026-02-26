from loguru import logger
from django.apps import AppConfig
from django.conf import settings
import sys


class TablesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tables"

    def ready(self):
        # ruff: noqa: F401
        import tables.signals.session_signals
        import tables.signals.crew_signals
        import tables.signals.graph_signals
        import tables.signals.telegram_signals
        import tables.signals.python_code_tool_config_signals
        import tables.signals.naive_rag_signals
        from tables.services.config_service import YamlConfigService
        from tables.services.converter_service import ConverterService
        from tables.services.redis_service import RedisService
        from tables.services.session_manager_service import SessionManagerService
        from tables.services.run_python_code_service import RunPythonCodeService
        from tables.services.realtime_service import RealtimeService
        from tables.services.webhook_trigger_service import WebhookTriggerService
        from tables.services.telegram_trigger_service import TelegramTriggerService
        from tables.import_export.registry import entity_registry
        from tables.import_export.strategies import (
            configs,
            python_tools,
            mcp_tools,
            agent,
            crew,
            graph,
            webhook,
            llm_models,
            tags,
        )

        if "runserver" in sys.argv:
            logger.info(f"{settings.DEBUG=}")

        redis_service = RedisService()
        converter_service = ConverterService()
        session_manager_service = SessionManagerService(
            redis_service=redis_service,
            converter_service=converter_service,
        )
        YamlConfigService()
        RunPythonCodeService(redis_service=redis_service)
        RealtimeService(
            redis_service=redis_service, converter_service=converter_service
        )
        WebhookTriggerService(session_manager_service=session_manager_service)
        TelegramTriggerService(session_manager_service=session_manager_service)

        # Register strategies for import/export entities
        entity_registry.register(llm_models.LLMModelStrategy())
        entity_registry.register(llm_models.EmbeddingModelStrategy())
        entity_registry.register(llm_models.RealtimeModelStrategy())
        entity_registry.register(llm_models.RealtimeTranscriptionModelStrategy())
        entity_registry.register(configs.LLMConfigStrategy())
        entity_registry.register(configs.EmbeddingConfigStrategy())
        entity_registry.register(configs.RealtimeConfigStrategy())
        entity_registry.register(configs.RealtimeTranscriptionConfigStrategy())
        entity_registry.register(python_tools.PythonCodeToolStrategy())
        entity_registry.register(mcp_tools.McpToolStrategy())
        entity_registry.register(agent.AgentStrategy())
        entity_registry.register(crew.CrewStrategy())
        entity_registry.register(graph.GraphStrategy())
        entity_registry.register(webhook.WebhookTriggerStrategy())
        entity_registry.register(tags.AgentTagStrategy())
        entity_registry.register(tags.CrewTagStrategy())
        entity_registry.register(tags.GraphTagStrategy())
        entity_registry.register(tags.LLMConfigTagStrategy())
        entity_registry.register(tags.LLMModelTagStrategy())
        entity_registry.register(tags.EmbeddingModelTagStrategy())
