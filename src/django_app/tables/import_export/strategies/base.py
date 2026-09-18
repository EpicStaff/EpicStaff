from typing import Any, Callable, Optional
from abc import ABC, abstractmethod

from django.db.models import Q

from tables.import_export.id_mapper import IDMapper
from tables.import_export.enums import EntityType
from tables.import_export.schemas import ImportSettings


class EntityImportExportStrategy(ABC):
    entity_type: EntityType

    # Define these in a subclass to enable CSV export for the entity.
    # CSV_FIELDS: list of column names written to the CSV header.
    # csv_row_mapper: transforms a raw exported dict into a flat CSV row.
    CSV_FIELDS: Optional[list[str]] = None
    csv_row_mapper: Optional[Callable[[dict], dict]] = None

    @abstractmethod
    def get_instance(self, entity_id: int) -> Optional[Any]:
        """Retrieve instance by ID"""
        pass

    @abstractmethod
    def extract_dependencies_from_instance(self, instance: Any) -> dict[str, list[int]]:
        """
        Extract dependencies from an instance.
        Returns: {entity_type: [id1, id2, ...]}
        """
        pass

    @abstractmethod
    def export_entity(self, instance: Any) -> dict:
        """Export single entity to dict"""
        pass

    @abstractmethod
    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> Any:
        pass

    def import_entity(
        self,
        data: dict,
        id_mapper: IDMapper,
        is_main: bool = False,
        settings: ImportSettings = None,
        **kwargs,
    ) -> Any:
        """
        Standard import - checks for existing first.
        """
        old_id = data.get("id")

        if old_id and id_mapper.has_mapping(self.entity_type, old_id):
            existing_id = id_mapper.get(self.entity_type, old_id)
            existing = self.get_instance(existing_id)
            return existing

        # The exported created_by references a user id from the source
        # system; it may not exist here (e.g. its org was deleted), which
        # would otherwise fail FK validation in create_entity. Drop it and
        # stamp the importing user on the freshly created instance instead.
        data = {k: v for k, v in data.items() if k != "created_by"}

        settings_kwargs = vars(settings) if settings is not None else {}
        create_kwargs = {**settings_kwargs, **kwargs}
        if is_main:
            instance = self.create_entity(data, id_mapper, **create_kwargs)
        else:
            existing = self.find_existing(data, id_mapper, org_id=kwargs.get("org_id"))
            if existing:
                return existing

            instance = self.create_entity(data, id_mapper, **create_kwargs)

        user = kwargs.get("user")
        if user is not None and hasattr(instance, "created_by_id"):
            instance.created_by = user
            instance.save(update_fields=["created_by"])

        return instance

    def find_existing(
        self, data: dict, id_mapper: IDMapper, org_id: int = None
    ) -> Optional[Any]:
        """
        Check if entity already exists. Override per entity type.
        Return existing instance or None.
        """
        return None

    def get_org_scope_q(self, org_id: int) -> Q:
        """Q applied to find_existing lookups to scope reuse to the active org.

        Default is global (no scoping). Override per org-scoped strategy.
        When org_id is None, returns Q() so direct/internal callers are
        unaffected.
        """
        return Q()

    def get_preview_data(self, instance: Any) -> dict:
        """
        Return lightweight preview data for summary.
        Override for custom preview fields.
        """
        return {"id": instance.id}
