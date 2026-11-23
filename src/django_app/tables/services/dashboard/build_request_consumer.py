from django.db import close_old_connections
from django.utils import timezone
from src.shared.redis_streams import DASHBOARD_BUILD_CONSUMER_GROUP, DASHBOARD_BUILD_STREAM
from tables.services.dashboard.report import build_due_reports
from tables.services.stream_request_consumer import StreamRequestConsumer
from utils.logger import logger


class DashboardBuildRequestConsumer(StreamRequestConsumer):
    stream = DASHBOARD_BUILD_STREAM
    group = DASHBOARD_BUILD_CONSUMER_GROUP
    description = "Dashboard build consumer"

    def _handle(self, entries: list) -> None:
        try:
            close_old_connections()
            built, failed = build_due_reports(timezone.now())
            if built or failed:
                logger.info("Dashboard reports built: {}, failed: {}", built, failed)
        except Exception:
            logger.exception("Dashboard build check failed")
        finally:
            close_old_connections()
            self._acknowledge([entry_id for entry_id, _fields in entries])
