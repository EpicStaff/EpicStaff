from src.shared.models import SessionAuditEvent


class RecordingAuditClient:
    """Stands in for AuditClient: keeps every emitted event instead of sending it to auditor."""

    def __init__(self):
        self.events: list[SessionAuditEvent] = []

    async def emit(self, event: SessionAuditEvent) -> None:
        self.events.append(event)

    async def shutdown(self) -> None:
        return None
