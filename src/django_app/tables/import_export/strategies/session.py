from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.serializers.session import (
    GraphSessionMessageExportSerializer,
    SessionExportSerializer,
)
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.models.session_models import Session


class SessionStrategy(EntityImportExportStrategy):
    entity_type = EntityType.SESSION

    def get_instance(self, entity_id: int) -> Session:
        return Session.objects.filter(id=entity_id).select_related("trigger", "principal").first()

    def get_preview_data(self, instance: Session) -> dict:
        return {"id": instance.id, "status": instance.status}

    def extract_dependencies_from_instance(self, instance: Session) -> dict:
        sub_ids = list(instance.subgraph_sessions.values_list("id", flat=True))
        return {EntityType.SESSION: sub_ids}

    def export_entity(self, instance: Session) -> dict:
        return {
            "session": SessionExportSerializer(instance).data,
            "messages": list(
                GraphSessionMessageExportSerializer(
                    instance.graphsessionmessage_set.all().order_by("created_at"),
                    many=True,
                ).data
            ),
        }

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs):
        raise NotImplementedError("Session export is read-only")
