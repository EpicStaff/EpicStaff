from django.db import transaction
from rest_framework.exceptions import PermissionDenied

from tables.models import Crew, EmbeddingConfig
from tables.models.knowledge_models.graphrag_models import GraphRag
from tables.models.knowledge_models.naive_rag_models import NaiveRag
from tables.models.rbac_models.rbac_enums import Permission, ResourceType

IN_USE_RESTRICTED = "in_use_restricted"
SAMPLE_LIMIT = 5


def _projects_items(config_ids, org_id):
    """PROJECTS bucket: Crew.embedding_config -- sample is the Crew itself."""
    items = {}
    for config_id, item_id, item_name in Crew.objects.filter(
        org_id=org_id, embedding_config_id__in=config_ids
    ).values_list("embedding_config_id", "id", "name"):
        items.setdefault(config_id, []).append({"id": item_id, "name": item_name})
    return items


def _knowledge_sources_items(config_ids, org_id):
    """KNOWLEDGE_SOURCES bucket: GraphRag.embedder + NaiveRag.embedder --
    two sources, one merged bucket. Sample shows the containing
    SourceCollection, matching llm_config_delete_service.py's convention."""
    items = {}

    graph_rag_rows = (
        GraphRag.objects.filter(
            base_rag_type__source_collection__org_id=org_id, embedder_id__in=config_ids
        )
        .values_list(
            "embedder_id",
            "base_rag_type__source_collection__collection_id",
            "base_rag_type__source_collection__collection_name",
        )
        .distinct()
    )
    naive_rag_rows = (
        NaiveRag.objects.filter(
            base_rag_type__source_collection__org_id=org_id, embedder_id__in=config_ids
        )
        .values_list(
            "embedder_id",
            "base_rag_type__source_collection__collection_id",
            "base_rag_type__source_collection__collection_name",
        )
        .distinct()
    )
    for config_id, item_id, item_name in list(graph_rag_rows) + list(naive_rag_rows):
        items.setdefault(config_id, []).append({"id": item_id, "name": item_name})
    return items


def get_usage(config_ids, org_id, effective):
    """{config_id: {blocked, by_resource_type: [...]}} across the two
    referencing buckets for EmbeddingConfig. See llm_config_delete_service.py
    for the shared shape/visibility rationale."""
    if not config_ids:
        return {}

    buckets = [
        (ResourceType.PROJECTS, _projects_items(config_ids, org_id)),
        (ResourceType.KNOWLEDGE_SOURCES, _knowledge_sources_items(config_ids, org_id)),
    ]

    usage = {}
    for config_id in config_ids:
        by_resource_type = []
        blocked = False
        for resource_type, items_by_config in buckets:
            items = items_by_config.get(config_id, [])
            total_count = len(items)
            can_read = effective.can(resource_type, Permission.READ)
            visible_items = items if can_read else []
            visible_count = len(visible_items)
            if total_count > visible_count:
                blocked = True
            by_resource_type.append(
                {
                    "resource_type": resource_type,
                    "visible_count": visible_count,
                    "visible_sample": visible_items[:SAMPLE_LIMIT],
                    "truncated": visible_count > SAMPLE_LIMIT,
                }
            )
        usage[config_id] = {"blocked": blocked, "by_resource_type": by_resource_type}
    return usage


def assert_embedding_config_deletable(config, org_id, effective):
    """Guard for single-object destroy -- mirrors the bulk-delete check so
    both paths enforce the same rule (a user can't bypass the block by
    deleting one-by-one)."""
    if get_usage([config.id], org_id, effective)[config.id]["blocked"]:
        raise PermissionDenied(IN_USE_RESTRICTED)


def bulk_delete_embedding_configs(ids, org_id, effective, dry_run=False):
    found = list(EmbeddingConfig.objects.filter(org_id=org_id, id__in=ids))
    found_ids = {config.id for config in found}
    not_found_ids = [i for i in ids if i not in found_ids]

    usage = get_usage(list(found_ids), org_id, effective)

    deleted_ids = []
    skipped_ids = []
    with transaction.atomic():
        for config in found:
            config_id = config.id  # capture before delete() nulls instance.pk
            if usage[config_id]["blocked"]:
                skipped_ids.append({"id": config_id, "reason": IN_USE_RESTRICTED})
                continue
            if not dry_run:
                config.delete()
            deleted_ids.append(config_id)

    return {
        "dry_run": dry_run,
        "deleted_count": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "not_found_ids": not_found_ids,
        "skipped_ids": skipped_ids,
        "usage": {str(config_id): entry for config_id, entry in usage.items()},
    }
