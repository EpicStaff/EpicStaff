from typing import Optional, Dict
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class EntityMapping:
    old_id: int
    new_id: int
    was_created: bool


class IDMapper:
    def __init__(self):
        self._mappings: Dict[str, Dict[int, EntityMapping]] = defaultdict(dict)

    def map(self, entity_type: str, old_id: int, new_id: int, was_created: bool = True):
        self._mappings[entity_type][old_id] = EntityMapping(
            old_id=old_id, new_id=new_id, was_created=was_created
        )

    def get(self, entity_type: str, old_id: int) -> int:
        if (
            entity_type not in self._mappings
            or old_id not in self._mappings[entity_type]
        ):
            raise ValueError(f"No mapping found for {entity_type}:{old_id}")
        return self._mappings[entity_type][old_id].new_id

    def get_or_none(self, entity_type: str, old_id: int) -> Optional[int]:
        mapping = self._mappings[entity_type].get(old_id)
        return mapping.new_id if mapping else None

    def has_mapping(self, entity_type: str, old_id: int) -> bool:
        return old_id in self._mappings[entity_type]

    def was_created(self, entity_type: str, old_id: int) -> bool:
        if (
            entity_type not in self._mappings
            or old_id not in self._mappings[entity_type]
        ):
            raise ValueError(f"No mapping found for {entity_type}:{old_id}")
        return self._mappings[entity_type][old_id].was_created

    def get_created_count(self, entity_type: str) -> int:
        return sum(
            1 for mapping in self._mappings[entity_type].values() if mapping.was_created
        )

    def get_reused_count(self, entity_type: str) -> int:
        return sum(
            1
            for mapping in self._mappings[entity_type].values()
            if not mapping.was_created
        )

    def get_new_ids(self, entity_type: str) -> list[int]:
        return [mapping.new_id for mapping in self._mappings[entity_type].values()]

    def get_created_ids(self, entity_type: str) -> list[int]:
        return [
            mapping.new_id
            for mapping in self._mappings[entity_type].values()
            if mapping.was_created
        ]

    def get_reused_ids(self, entity_type: str) -> list[int]:
        return [
            mapping.new_id
            for mapping in self._mappings[entity_type].values()
            if not mapping.was_created
        ]

    def get_detailed_summary(self, registry) -> dict:
        summary = {}

        for entity_type in self._mappings:
            strategy = registry.get_strategy(entity_type)

            created_mappings = [
                m for m in self._mappings[entity_type].values() if m.was_created
            ]
            reused_mappings = [
                m for m in self._mappings[entity_type].values() if not m.was_created
            ]

            summary[entity_type] = {
                "total": len(self._mappings[entity_type]),
                "created": {
                    "count": len(created_mappings),
                    "items": [
                        self._serialize_entity(strategy, m.new_id)
                        for m in created_mappings
                    ],
                },
                "reused": {
                    "count": len(reused_mappings),
                    "items": [
                        self._serialize_entity(strategy, m.new_id)
                        for m in reused_mappings
                    ],
                },
            }

        return summary

    def _serialize_entity(self, strategy, entity_id):
        instance = strategy.get_instance(entity_id)
        if not instance:
            return {"id": entity_id, "error": "Not found"}

        return strategy.get_preview_data(instance)
