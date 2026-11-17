"""Knowledge entries of a surface: the collection it searches and its search configs.

Shared by shared and owned surfaces and by the inline surfaces of agent and task
nodes. Export, create and the reuse key all go through these functions, so they
cannot disagree on what an entry holds.
"""

import json
from decimal import Decimal

from agents.serializers.surface_serializers import (
    SurfaceGraphBasicSearchConfigWriteSerializer,
    SurfaceGraphDriftSearchConfigWriteSerializer,
    SurfaceGraphGlobalSearchConfigWriteSerializer,
    SurfaceGraphLocalSearchConfigWriteSerializer,
    SurfaceNaiveSearchConfigWriteSerializer,
)
from django.core.exceptions import ObjectDoesNotExist
from django.forms.models import model_to_dict
from rest_framework.exceptions import ValidationError

from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.models.base_models import SOFT_DELETE_FIELD_NAMES
from tables.models.knowledge_models import SourceCollection

# The serializers the surface API checks each search config with: an import is held
# to the same limits. Each takes only its own fields and fills the model defaults.
_SEARCH_CONFIG_SERIALIZERS = {
    "naive_search_config": SurfaceNaiveSearchConfigWriteSerializer,
    "graph_basic_search_config": SurfaceGraphBasicSearchConfigWriteSerializer,
    "graph_local_search_config": SurfaceGraphLocalSearchConfigWriteSerializer,
    "graph_global_search_config": SurfaceGraphGlobalSearchConfigWriteSerializer,
    "graph_drift_search_config": SurfaceGraphDriftSearchConfigWriteSerializer,
}
SEARCH_CONFIG_RELATIONS = tuple(_SEARCH_CONFIG_SERIALIZERS)
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


def _row_entry(row) -> dict:
    """Return the collection id and search configs of one knowledge row."""
    entry = {"collection": row.collection_id}
    for relation in SEARCH_CONFIG_RELATIONS:
        try:
            entry[relation] = _config_values(getattr(row, relation))
        except ObjectDoesNotExist:
            entry[relation] = None
    return entry


def serialize_knowledge(knowledge_rows) -> list[dict]:
    """Return each knowledge row as `{"collection": id, "collection_name": name,
    "<relation>": values | None}`.

    The name lets an import into another instance tell a same-id collection that is
    a different one. Pass rows with `collection` and the search configs selected, or
    each row costs a query per relation. Sorted by collection, so an export of the
    same surface is always the same.
    """
    entries = []
    for row in knowledge_rows:
        entry = _row_entry(row)
        entry["collection_name"] = row.collection.collection_name
        entries.append(entry)
    return sorted(entries, key=lambda entry: entry["collection"])


def resolve_collection_id(
    old_id: int | None, id_mapper: IDMapper, org_id: int | None, name: str | None = None
) -> int | None:
    """Return the collection a link points at after import, or None when there is none.

    The collection this import created or reused when the file carried it;
    otherwise the same id when it names a collection of the importing org (an
    import back into the same instance) and, when the file gives the collection's
    `name`, that collection still has it; otherwise None, and the link is dropped.
    Files written before links carried the name give None and relink by id alone.
    """
    if old_id is None:
        return None
    mapped_id = id_mapper.get_or_none(EntityType.SOURCE_COLLECTION, old_id)
    if mapped_id is not None:
        return mapped_id
    same_id = SourceCollection.objects.filter(pk=old_id, org_id=org_id)
    if name is not None:
        same_id = same_id.filter(collection_name=name)
    if same_id.exists():
        return old_id
    return None


def _resolved_entries(entries: list[dict], id_mapper: IDMapper, org_id: int | None):
    """Yield `(collection id, entry)` for each entry an import keeps.

    An entry whose collection does not resolve is dropped, and so is one whose
    collection an earlier entry already linked: a surface links a collection once.
    """
    linked = set()
    for entry in entries:
        collection_id = resolve_collection_id(
            entry.get("collection"), id_mapper, org_id, entry.get("collection_name")
        )
        if collection_id is None or collection_id in linked:
            continue
        linked.add(collection_id)
        yield collection_id, entry


def create_knowledge(
    knowledge_model,
    owner_kwargs: dict,
    entries: list[dict],
    id_mapper: IDMapper,
    org_id: int | None,
) -> None:
    """Create the knowledge rows and search configs of one surface.

    An entry whose collection does not resolve, or is already linked, is dropped.
    A search config is checked by the serializer the surface API uses: it takes only
    the config's own settings from the file, ignores any other key, and gives a
    setting the file leaves out its default.

    Raises:
        ValidationError: A search config holds a value the surface API refuses;
            keyed by the collection and the config. The import's transaction rolls
            back, so nothing of the file is stored.
    """
    for collection_id, entry in _resolved_entries(entries, id_mapper, org_id):
        configs = _validated_search_configs(entry)
        row = knowledge_model.objects.create(collection_id=collection_id, **owner_kwargs)
        for relation, values in configs.items():
            config_model = knowledge_model._meta.get_field(relation).related_model
            config_model.objects.create(**values, **{_KNOWLEDGE_FIELD: row})


def _validated_search_configs(entry: dict) -> dict:
    """Return each search config the entry gives a value for, validated."""
    validated = {}
    for relation, serializer_class in _SEARCH_CONFIG_SERIALIZERS.items():
        values = entry.get(relation)
        if not values:
            continue
        serializer = serializer_class(data=values)
        if not serializer.is_valid():
            collection_label = entry.get("collection_name") or entry.get("collection")
            raise ValidationError(
                {f'Knowledge of collection "{collection_label}"': {relation: serializer.errors}}
            )
        validated[relation] = serializer.validated_data
    return validated


def _entry_key(collection_id: int, entry: dict) -> tuple[int, str]:
    # The collection's name is left out: two links to one collection are equal.
    configs = {relation: entry.get(relation) for relation in SEARCH_CONFIG_RELATIONS}
    return collection_id, json.dumps(configs, sort_keys=True)


def knowledge_key_of_entries(
    entries: list[dict], id_mapper: IDMapper, org_id: int | None
) -> frozenset:
    """Return the knowledge an exported surface would get, in a comparable form.

    Holds only the entries `create_knowledge` would keep, so it equals
    `knowledge_key_of_rows` of the surface an import of these entries creates.
    """
    return frozenset(
        _entry_key(collection_id, entry)
        for collection_id, entry in _resolved_entries(entries, id_mapper, org_id)
    )


def knowledge_key_of_rows(knowledge_rows) -> frozenset:
    """Return `knowledge_key_of_entries` for the knowledge rows of a stored surface."""
    return frozenset(_entry_key(row.collection_id, _row_entry(row)) for row in knowledge_rows)
