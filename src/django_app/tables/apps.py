from loguru import logger
from django.apps import AppConfig
from django.conf import settings
import sys


class TablesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tables"

    def ready(self):
        from tables.services.config_service import YamlConfigService
        from tables.services.converter_service import ConverterService
        from tables.services.redis_service import RedisService
        from tables.services.session_manager_service import SessionManagerService
        from tables.services.run_python_code_service import RunPythonCodeService
        from tables.services.realtime_service import RealtimeService

        if "runserver" in sys.argv:
            logger.info(f"{settings.DEBUG=}")

        redis_service = RedisService()
        converter_service = ConverterService()
        SessionManagerService(
            redis_service=redis_service,
            converter_service=converter_service,
        )
        YamlConfigService()
        RunPythonCodeService(redis_service=redis_service)
        RealtimeService(
            redis_service=redis_service, converter_service=converter_service
        )
