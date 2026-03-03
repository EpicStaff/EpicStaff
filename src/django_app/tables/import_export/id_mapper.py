from typing import Optional
from collections import defaultdict


class IDMapper:

    def __init__(self):
        self._mappings = defaultdict(dict)

    def map(self, entity_type: str, old_id: int, new_id: int):
        self._mappings[entity_type][old_id] = new_id

    def get(self, entity_type: str, old_id: int) -> int:
        return self._mappings[entity_type][old_id]

    def get_or_none(self, entity_type: str, old_id: int) -> Optional[int]:
        return self._mappings[entity_type].get(old_id)

    def get_new_ids(self, entity_type: str) -> list[int]:
        return list(self._mappings[entity_type].values())
