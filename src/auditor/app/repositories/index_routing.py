"""Which index of a domain's family an incoming audit event is written to."""

from datetime import UTC, datetime

from app.domains.base import IndexSpec
from loguru import logger
from src.shared.models import BaseAuditEvent
from src.shared.retention import RETENTION_CHOICES, audit_tier

_UNLIMITED_RETENTION_DAYS = 0


def index_name_for(index: IndexSpec, event: BaseAuditEvent, received_at: datetime) -> str:
    """Return the index `event` is written to: `{index.name}-{tier}-{yyyy.mm}`.

    The tier is the event's `retention_days`. A value outside RETENTION_CHOICES is kept
    forever and logged: routing it to a shorter tier would delete audit history earlier
    than anyone chose.

    Args:
        received_at: When auditor received the event. Must be timezone-aware; the month
            is taken in UTC. The event's own `event_time` is deliberately not used, so a
            sender's clock skew or a late delivery cannot route into a read-only month.
    """
    retention_days = event.retention_days
    if retention_days not in RETENTION_CHOICES:
        logger.warning(
            "Audit event {} has retention_days={}, not one of {}; storing it as unlimited.",
            event.id,
            retention_days,
            RETENTION_CHOICES,
        )
        retention_days = _UNLIMITED_RETENTION_DAYS
    month = received_at.astimezone(UTC).strftime("%Y.%m")
    return f"{index.name}-{audit_tier(retention_days)}-{month}"
