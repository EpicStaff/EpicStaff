from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from tables.models import EmbeddingConfig, EmbeddingModel
from tables.models.rbac_models.rbac_enums import Permission, ResourceType

IN_USE_RESTRICTED = "in_use_restricted"
PREDEFINED = "predefined"
SAMPLE_LIMIT = 5


def _embedding_configs_items(model_ids, org_id):
    """Distinct EmbeddingConfig rows referencing each model via
    EmbeddingConfig.model (on_delete=SET_NULL -- unlike LLMModel/LLMConfig,
    deleting the Model only nulls the reference, it doesn't cascade-delete
    the Config). A plain one-hop visibility check is therefore sufficient
    here -- no need for the cascade-aware check in
    llm_model_delete_service.py."""
    rows = EmbeddingConfig.objects.filter(
        model_id__in=model_ids, org_id=org_id
    ).values_list("model_id", "id", "custom_name")
    items = {}
    for model_id, config_id, config_name in rows:
        items.setdefault(model_id, []).append({"id": config_id, "name": config_name})
    return items


def get_usage(model_ids, org_id, effective):
    """{model_id: {blocked, by_resource_type: [...]}} -- one-hop LLM_CONFIGS
    bucket (see module docstring for why this is sufficient for
    EmbeddingModel, unlike LLMModel)."""
    if not model_ids:
        return {}

    items_by_model = _embedding_configs_items(model_ids, org_id)
    can_read = effective.can(ResourceType.LLM_CONFIGS, Permission.READ)

    usage = {}
    for model_id in model_ids:
        items = items_by_model.get(model_id, [])
        total_count = len(items)
        visible_items = items if can_read else []
        visible_count = len(visible_items)
        usage[model_id] = {
            "blocked": total_count > visible_count,
            "by_resource_type": [
                {
                    "resource_type": ResourceType.LLM_CONFIGS,
                    "visible_count": visible_count,
                    "visible_sample": visible_items[:SAMPLE_LIMIT],
                    "truncated": visible_count > SAMPLE_LIMIT,
                }
            ],
        }
    return usage


def assert_embedding_model_deletable(model, org_id, effective):
    """Guard for single-object destroy -- mirrors the bulk-delete check.
    Only called for non-predefined models (predefined block handled
    separately, same as before this feature existed)."""
    if get_usage([model.id], org_id, effective)[model.id]["blocked"]:
        raise PermissionDenied(IN_USE_RESTRICTED)


def bulk_delete_embedding_models(ids, org_id, effective, dry_run=False):
    found = list(
        EmbeddingModel.objects.filter(id__in=ids).filter(
            Q(is_custom=False) | Q(org_id=org_id)
        )
    )
    found_ids = {model.id for model in found}
    not_found_ids = [i for i in ids if i not in found_ids]

    candidate_ids = [model.id for model in found if not model.predefined]
    usage = get_usage(candidate_ids, org_id, effective)

    deleted_ids = []
    skipped_ids = []
    with transaction.atomic():
        for model in found:
            model_id = model.id  # capture before delete() nulls instance.pk
            if model.predefined:
                skipped_ids.append({"id": model_id, "reason": PREDEFINED})
                continue
            if usage[model_id]["blocked"]:
                skipped_ids.append({"id": model_id, "reason": IN_USE_RESTRICTED})
                continue
            if not dry_run:
                model.delete()
            deleted_ids.append(model_id)

    return {
        "dry_run": dry_run,
        "deleted_count": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "not_found_ids": not_found_ids,
        "skipped_ids": skipped_ids,
        "usage": {str(model_id): entry for model_id, entry in usage.items()},
    }
