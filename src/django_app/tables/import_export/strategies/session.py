from collections.abc import Iterable

from django.db.models import QuerySet

from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.serializers.session import (
    GraphSessionMessageExportSerializer,
    SessionExportSerializer,
)
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.models.graph_models import GraphSessionMessage
from tables.models.session_models import Session

# Exactly what SessionExportSerializer reads: a session's variables and status data,
# and its flow's metadata, can be large and are never exported.
_SESSION_EXPORT_COLUMNS = (
    "id",
    "status",
    "entrypoint",
    "created_at",
    "finished_at",
    "token_usage",
    "graph",
    "graph__name",
    "trigger__trigger_type",
    "trigger__node_name",
    "principal__kind",
    "principal__user",
    "principal__api_key",
    "principal__api_key__name",
    "principal__email",
    "principal__plugin_identifier",
)
_MESSAGE_EXPORT_COLUMNS = (
    "id",
    "session",
    "created_at",
    "name",
    "execution_order",
    "uuid",
    "message_data",
    "node_type",
)


class SessionStrategy(EntityImportExportStrategy):
    entity_type = EntityType.SESSION

    @staticmethod
    def export_sessions() -> QuerySet:
        """Every session, loading only what its export entry holds. Not org-scoped."""
        return Session.objects.select_related("trigger", "principal__api_key", "graph").only(
            *_SESSION_EXPORT_COLUMNS
        )

    @staticmethod
    def export_messages() -> QuerySet:
        """Every session message, loading only what its export entry holds. Not org-scoped."""
        return GraphSessionMessage.objects.only(*_MESSAGE_EXPORT_COLUMNS)

    @staticmethod
    def export_entry(session: Session, messages: Iterable[GraphSessionMessage]) -> dict:
        """The export entry of `session`; `messages` are its own, oldest first."""
        return {
            "session": SessionExportSerializer(session).data,
            "messages": list(GraphSessionMessageExportSerializer(messages, many=True).data),
        }

    def get_instance(self, entity_id: int) -> Session:
        return self.export_sessions().filter(id=entity_id).first()

    def get_preview_data(self, instance: Session) -> dict:
        return {"id": instance.id, "status": instance.status}

    def extract_dependencies_from_instance(self, instance: Session) -> dict:
        sub_ids = list(instance.subgraph_sessions.values_list("id", flat=True))
        return {EntityType.SESSION: sub_ids}

    def export_entity(self, instance: Session) -> dict:
        return self.export_entry(
            instance,
            self.export_messages().filter(session=instance).order_by("created_at", "id"),
        )

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs):
        raise NotImplementedError("Session export is read-only")
