from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from tables.models import LLMConfig, LLMModel
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.services import llm_config_delete_service

IN_USE_RESTRICTED = "in_use_restricted"
PREDEFINED = "predefined"
SAMPLE_LIMIT = 5


def _llm_configs_items(model_ids, org_id):
    """Distinct LLMConfig rows referencing each model via LLMConfig.model
    (on_delete=CASCADE -- unlike every other Model/Config relationship in
    this rollout, deleting the Model force-deletes these rows)."""
    rows = LLMConfig.objects.filter(model_id__in=model_ids, org_id=org_id).values_list(
        "model_id", "id", "custom_name"
    )
    items = {}
    for model_id, config_id, config_name in rows:
        items.setdefault(model_id, []).append({"id": config_id, "name": config_name})
    return items


def get_usage(model_ids, org_id, effective):
    """{model_id: {blocked, by_resource_type: [...]}}.

    `LLMConfig.model` is CASCADE, not SET_NULL -- deleting an LLMModel force-
    deletes every LLMConfig referencing it. A plain one-hop "is the LLMConfig
    visible" check is too weak here: that visibility check is against the
    SAME resource_type (LLM_CONFIGS) the deleting user already has DELETE on,
    so it's nearly always true and protects nothing. The real risk is that
    those cascaded LLMConfig rows are themselves in use by Agents/Crews/
    Flows/Knowledge the user can't see -- exactly what
    `llm_config_delete_service.get_usage` already checks. So this reuses that
    function as a black box (batched once for every referencing config
    across all requested models) rather than re-deriving the same logic --
    a deliberate, bounded exception to the "one-hop only" principle used
    everywhere else in this rollout, justified specifically by the CASCADE
    relationship (contrast with `embedding_model_delete_service.py`, where
    `EmbeddingConfig.model` is SET_NULL and a plain one-hop check is enough).
    """
    if not model_ids:
        return {}

    items_by_model = _llm_configs_items(model_ids, org_id)
    can_read = effective.can(ResourceType.LLM_CONFIGS, Permission.READ)

    all_config_ids = [
        item["id"] for items in items_by_model.values() for item in items
    ]
    config_usage = (
        llm_config_delete_service.get_usage(all_config_ids, org_id, effective)
        if all_config_ids
        else {}
    )

    usage = {}
    for model_id in model_ids:
        items = items_by_model.get(model_id, [])
        total_count = len(items)
        visible_items = items if can_read else []
        visible_count = len(visible_items)
        any_cascaded_config_blocked = any(
            config_usage.get(item["id"], {}).get("blocked", False) for item in items
        )
        usage[model_id] = {
            "blocked": (total_count > visible_count) or any_cascaded_config_blocked,
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


def assert_llm_model_deletable(model, org_id, effective):
    """Guard for single-object destroy -- mirrors the bulk-delete check so
    both paths enforce the same rule. Only called for non-predefined models
    (the caller/perform_destroy handles the predefined block separately,
    same as before this feature existed)."""
    if get_usage([model.id], org_id, effective)[model.id]["blocked"]:
        raise PermissionDenied(IN_USE_RESTRICTED)


def bulk_delete_llm_models(ids, org_id, effective, dry_run=False):
    # Mirrors OrgScopedHybridViewSetMixin's own visibility: predefined
    # (global, org=None) rows plus this org's own custom rows.
    found = list(
        LLMModel.objects.filter(id__in=ids).filter(
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
