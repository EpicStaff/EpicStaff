from collections.abc import Iterator

from django.apps import apps as installed_apps
from django.apps.registry import Apps
from django.conf import settings
from django.db.models import Model
from tables.models.base_models import SandboxExecutionTimeoutMixin
from utils.logger import logger


def clamp_stored_execution_timeouts(app_registry: Apps, using: str) -> int:
    """Lower every node execution timeout stored above the sandbox ceiling to the ceiling.

    SANDBOX_EXECUTION_TIMEOUT can be lowered after nodes were saved, which would leave
    them above what the sandbox enforces. This runs after every `migrate` (each
    django_app start) so the stored value, and everything derived from it, matches
    the limit actually applied.

    One `UPDATE` per node model rather than `save()`: the change is deployment
    configuration, not an edit. `content_hash` is derived from the current field
    values, so the next read returns a hash that matches the clamped row, and neither
    path bumps the graph's `save_version`. `save()` would also stamp `updated_at` on
    the node and its graph, reordering "recently edited" lists, and re-register
    webhook trigger nodes with the webhook service through their `post_save` handler.
    Soft-deleted rows are clamped too, so a restore cannot bring an old value back.

    Args:
        app_registry: The registry `post_migrate` passes, describing the schema the
            database actually has after this migrate. A node model whose
            `execution_timeout` column does not exist in it (a migrate back to before
            the column) is skipped.
        using: Alias of the database that was migrated.

    Returns:
        The number of rows lowered to the ceiling.
    """
    ceiling = settings.SANDBOX_MAX_EXECUTION_TIMEOUT_MINUTES
    clamped = sum(
        model._base_manager.using(using)
        .filter(execution_timeout__gt=ceiling)
        .update(execution_timeout=ceiling)
        for model in _models_storing_execution_timeout(app_registry)
    )
    if clamped:
        logger.info(
            "Lowered {} node execution timeout(s) to the sandbox ceiling of {} min.",
            clamped,
            ceiling,
        )
    return clamped


def _models_storing_execution_timeout(app_registry: Apps) -> Iterator[type[Model]]:
    # Historical models in `app_registry` drop the mixin, so the installed models
    # say which nodes carry the field; a node gaining the mixin is covered without a
    # change here.
    for installed_model in installed_apps.get_models():
        if not issubclass(installed_model, SandboxExecutionTimeoutMixin):
            continue
        try:
            model = app_registry.get_model(installed_model._meta.label)
        except LookupError:
            continue
        if any(field.name == "execution_timeout" for field in model._meta.concrete_fields):
            yield model
