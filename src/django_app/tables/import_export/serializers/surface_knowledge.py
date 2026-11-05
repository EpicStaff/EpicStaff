"""Knowledge entries of a surface: the collection it searches and its search configs.

Shared by shared and owned surfaces and by the inline surfaces of agent and task
nodes. Export, create and the reuse key all go through these functions, so they
cannot disagree on what an entry holds.
"""

import json
from decimal import Decimal

from django.core.exceptions import ObjectDoesNotExist
from django.forms.models import model_to_dict

from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.models.base_models import SOFT_DELETE_FIELD_NAMES
from tables.models.knowledge_models import SourceCollection

SEARCH_CONFIG_RELATIONS = (
    "naive_search_config",
    "graph_basic_search_config",
    "graph_local_search_config",
    "graph_global_search_config",
    "graph_drift_search_config",
)
# Prefetch for a surface queryset, so its knowledge key costs no query per surface.
KNOWLEDGE_PREFETCH = (
    "knowledge",
    *(f"knowledge__{relation}" for relation in SEARCH_CONFIG_RELATIONS),
)
# Every search config model points back at its knowledge row through this field.
_KNOWLEDGE_FIELD = "surface_knowledge"
_CONFIG_EXCLUDED_FIELDS = ("id", _KNOWLEDGE_FIELD, *SOFT_DELETE_FIELD_NAMES)


def _config_values(config) -> dict:
    values = model_to_dict(config, exclude=_CONFIG_EXCLUDED_FIELDS)
    # A Decimal is not JSON; as text it also compares equal to the exported value.
    return {
        name: str(value) if isinstance(value, Decimal) else value for name, value in values.items()
    }


def serialize_knowledge(knowledge_rows) -> list[dict]:
    """Return each knowledge row as `{"collection": id, "<relation>": values | None}`.

    Sorted by collection, so an export of the same surface is always the same.
    """
    entries = []
    for row in knowledge_rows:
        entry = {"collection": row.collection_id}
        for relation in SEARCH_CONFIG_RELATIONS:
            try:
                entry[relation] = _config_values(getattr(row, relation))
            except ObjectDoesNotExist:
                entry[relation] = None
        entries.append(entry)
    return sorted(entries, key=lambda entry: entry["collection"])


def resolve_collection_id(
    old_id: int | None, id_mapper: IDMapper, org_id: int | None
) -> int | None:
    """Return the collection a link points at after import, or None when there is none.

    The collection this import created or reused when the file carried it;
    otherwise the same id when it names a collection of the importing org (an
    import back into the same instance); otherwise None, and the link is dropped.
    """
    if old_id is None:
        return None
    mapped_id = id_mapper.get_or_none(EntityType.SOURCE_COLLECTION, old_id)
    if mapped_id is not None:
        return mapped_id
    if SourceCollection.objects.filter(pk=old_id, org_id=org_id).exists():
        return old_id
    return None


def create_knowledge(
    knowledge_model,
    owner_kwargs: dict,
    entries: list[dict],
    id_mapper: IDMapper,
    org_id: int | None,
) -> None:
    """Create the knowledge rows and search configs of one surface.

    An entry whose collection does not resolve is dropped.
    """
    for entry in entries:
        collection_id = resolve_collection_id(entry.get("collection"), id_mapper, org_id)
        if collection_id is None:
            continue
        row = knowledge_model.objects.create(collection_id=collection_id, **owner_kwargs)
        for relation in SEARCH_CONFIG_RELATIONS:
            values = entry.get(relation)
            if not values:
                continue
            config_model = knowledge_model._meta.get_field(relation).related_model
            config_model.objects.create(**{_KNOWLEDGE_FIELD: row}, **values)


def _entry_key(collection_id: int, entry: dict) -> tuple[int, str]:
    configs = {relation: entry.get(relation) for relation in SEARCH_CONFIG_RELATIONS}
    return collection_id, json.dumps(configs, sort_keys=True)


def knowledge_key_of_entries(
    entries: list[dict], id_mapper: IDMapper, org_id: int | None
) -> frozenset:
    """Return the knowledge an exported surface would get, in a comparable form.

    Holds only the entries `create_knowledge` would keep, so it equals
    `knowledge_key_of_rows` of the surface an import of these entries creates.
    """
    keys = set()
    for entry in entries:
        collection_id = resolve_collection_id(entry.get("collection"), id_mapper, org_id)
        if collection_id is not None:
            keys.add(_entry_key(collection_id, entry))
    return frozenset(keys)


def knowledge_key_of_rows(knowledge_rows) -> frozenset:
    """Return `knowledge_key_of_entries` for the knowledge rows of a stored surface."""
    return frozenset(
        _entry_key(entry["collection"], entry) for entry in serialize_knowledge(knowledge_rows)
    )
