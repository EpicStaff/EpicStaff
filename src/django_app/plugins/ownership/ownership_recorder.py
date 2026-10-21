"""Which rows a plugin's service account owns: every root it creates in an organization.

An ownable root is a model of the recycle bin (`bin_resources()`) or of
`EXTRA_OWNABLE_MODELS`. While the current request scope holds a service account, every new
row of one is recorded as a `PluginOwnedResource`, on behalf of a person or not, in the
transaction that created it (a rollback removes both). Deleting a root deletes its row, in the
transaction of the delete: one query per deleted object, or per queryset however many rows it
deletes.

Rows arrive two ways: `post_save(created=True)`, and `tables.signals.rows_bulk_created` for a
`bulk_create`, which sends no `post_save`. Adding an ownable root model: list it in the bin
registry or in `EXTRA_OWNABLE_MODELS`, and make each `bulk_create` of it send
`rows_bulk_created`; the ownership guards in the plugin tests fail until both are done.
"""

from collections.abc import Callable, Iterable
from functools import cache
from weakref import WeakSet

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model, QuerySet
from django.db.models.signals import post_save, pre_delete
from rbac.models import Organization
from tables.services.recycle_bin.registry import bin_resources
from tables.signals import rows_bulk_created

from plugins.identity.principals import PluginServiceAccountPrincipal
from plugins.models import PluginOwnedResource
from plugins.ownership.request_scope import CreatedRoot, current_scope

# Organization-owned roots outside the recycle bin that a service account can create.
EXTRA_OWNABLE_MODELS = (
    "tables.LLMConfig",
    "tables.EmbeddingConfig",
    "tables.RealtimeConfig",
    "tables.RealtimeTranscriptionConfig",
    "tables.OpenAIRealtimeConfig",
    "tables.ElevenLabsRealtimeConfig",
    "tables.GeminiRealtimeConfig",
    "tables.LLMModel",
    "tables.EmbeddingModel",
    "tables.RealtimeModel",
    "tables.RealtimeTranscriptionModel",
    "tables.StorageFile",
)
# A queryset delete sends `pre_delete` once per row. The ownership rows of every row it
# matches go at its first signal; the querysets already handled are remembered here (until
# they are garbage collected) so the signals that follow cost nothing.
_forgotten_querysets: WeakSet = WeakSet()
# Rows of an ownable model that are owned. A folder is a container the organization's own
# files live in: owning it would let a later purge of the plugin's rows take them along.
OWNED_ROWS: dict[str, Callable[[Model], bool]] = {
    "tables.StorageFile": lambda row: row.item_type == "file",
}


@cache
def ownable_models() -> tuple[type[Model], ...]:
    """Every ownable root model; call once the apps are loaded."""
    bin_models = [resource.model for resource in bin_resources().values()]
    extra_models = [apps.get_model(label) for label in EXTRA_OWNABLE_MODELS]
    return tuple(dict.fromkeys([*bin_models, *extra_models]))


def connect_ownership_recorder() -> None:
    """Connect the recorder to every ownable root; `PluginsConfig.ready()` calls it once."""
    for model in ownable_models():
        label = model._meta.label
        post_save.connect(
            _record_created, sender=model, dispatch_uid=f"plugins-ownership-created-{label}"
        )
        pre_delete.connect(
            _forget_deleted, sender=model, dispatch_uid=f"plugins-ownership-deleted-{label}"
        )
    rows_bulk_created.connect(_record_bulk_created, dispatch_uid="plugins-ownership-bulk")


def _record_created(sender, instance, created, raw=False, **kwargs) -> None:
    if not created or raw:
        return
    scope = current_scope()
    if scope is None or scope.principal is None:
        return
    _record(sender, [instance], scope)


def _record_bulk_created(sender, queryset, **kwargs) -> None:
    scope = current_scope()
    if scope is None or scope.principal is None or sender not in ownable_models():
        return
    _record(sender, list(queryset), scope)


def _forget_deleted(sender, instance, origin=None, **kwargs) -> None:
    # An organization delete takes its ownership rows along by cascade; asking for each of
    # its resources one by one would only slow it down.
    if isinstance(origin, Organization):
        return
    owned = PluginOwnedResource.objects.filter(
        content_type=ContentType.objects.get_for_model(sender)
    )
    # Deleting a queryset deletes exactly the rows it matches, as no ownable root cascades
    # from a row of its own model (the ownership guards check it): one query covers them all.
    if isinstance(origin, QuerySet) and origin.model is sender:
        if origin not in _forgotten_querysets:
            owned.filter(object_id__in=origin.values("pk")).delete()
            _forgotten_querysets.add(origin)
        return
    owned.filter(object_id=instance.pk).delete()


def _record(model: type[Model], rows: Iterable[Model], scope) -> None:
    principal: PluginServiceAccountPrincipal = scope.principal
    is_owned = OWNED_ROWS.get(model._meta.label, lambda row: True)
    owned = [row for row in rows if is_owned(row)]
    if not owned:
        return
    content_type = ContentType.objects.get_for_model(model)
    PluginOwnedResource.objects.bulk_create(
        PluginOwnedResource(
            org_id=principal.pinned_org_id,
            grant_id=principal.grant_id,
            plugin_identifier=principal.plugin_identifier,
            content_type=content_type,
            object_id=row.pk,
            on_behalf_of=principal.person,
        )
        for row in owned
    )
    scope.created.extend(
        CreatedRoot(model_label=model._meta.label, pk=row.pk, label=_name_of(row)) for row in owned
    )


def _name_of(row: Model) -> str | None:
    name = getattr(row, "name", None)
    return name if isinstance(name, str) else None
