"""Deleting for good what a plugin owns in an organization.

Each owned root goes the way a person's delete would take it, then the recycle bin's purge:
a recycle-bin root is binned and purged, a file is binned through storage and purged, a venv or
custom library is deleted in the sandbox (its wheels with it) and then its binding, and any
other root without a bin (a configuration) is hard-deleted. Nothing is left in the recycle bin.
What the organization's own rows lose is what they lose when a person deletes the item: a
link with SET_NULL is cleared (an agent loses its LLM config, a default-model setting is
emptied), and children that cascade go with the root. A delete that would reach another
organization's row is refused (`CascadeOrgGuard`), and that row is kept. A model row that a
configuration the plugin does not own still uses is kept too, and only its ownership row goes.

A venv that code some tool or node owns still runs in, and a custom library some venv of the
organization still names, wait instead of being refused: the plugin's own tools and flows go
before them (their code with them), so what still uses them once nothing else is left is the
organization's. Code no tool or node owns any more does not count: it runs nowhere, and goes
with the venv. That holds because every creator of code inserts it in the same transaction as
its owner, so no other transaction ever sees code that is about to get one. Which venvs name a
library only the sandbox can tell: a pass reads it once, before its first row, and under each
row's lock checks only which of those venvs are still there. Only those usage reads are out of
the lock: deleting a venv or custom library still calls the sandbox inside the row's
transaction, under the organization's lock, so the binding goes in the transaction that removed
its resource. A rollback after the remove leaves the binding, and a later pass, told the
resource is gone (`ClientNotFoundError`), drops it. The caller that ends the purge
then gives them to the organization in two steps: `plan_hand_over` asks the sandbox before any
lock is taken, and `hand_over`, in the caller's locking transaction, checks the database side
again and drops their ownership rows; they stay as they are, and the caller reports which
ones. The list is read from the ownership rows themselves, so it needs no store of its own
between the hourly passes.

One row per transaction, so a row that fails rolls back alone. A failed row is left alone for
`FAILED_ROW_RETRY_SECONDS`. Users of a resource go before what they use (`owned_purge_order`).

Adding an ownable model: classify it in `ownership_recorder`; a recycle-bin root takes its
place from the bin's `EMPTY_ORDER` by itself, any other model is named in
`EXTRA_PURGE_ORDER`, and a binding of a resource another service holds is named in
`PROXIED_ROOT_SERVICES`. `test_owned_resource_purger.py` fails until it is.
"""

import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from functools import cache
from types import MappingProxyType

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache as shared_cache
from django.db import router, transaction
from django.db.models import Model, Q, QuerySet
from django.db.models.deletion import Collector
from foundation.transport.http.errors import ClientError, ClientNotFoundError
from packaging.utils import canonicalize_name
from proxies.sandbox.models import SandboxCustomLibraryBinding, SandboxVenvBinding
from proxies.sandbox.services import CustomLibraryService, VenvService
from rbac.models import Organization
from tables.models import Graph, PythonCode, Session, StorageFile
from tables.services.cascade_org_guard import CascadeOrgGuard
from tables.services.python_code_cleanup_service import PythonCodeCleanupService
from tables.services.recycle_bin.deleting import move_to_recycle_bin
from tables.services.recycle_bin.empty_service import EMPTY_ORDER
from tables.services.recycle_bin.purge_service import PurgeService
from tables.services.recycle_bin.registry import bin_resources
from tables.services.recycle_bin.sources import RecycleBinSource
from tables.services.storage_service import get_storage_manager
from tables.services.storage_service.recycle_bin import StorageRecycleBinService
from utils.exceptions import CustomAPIExeption
from utils.logger import logger

from plugins.models import PluginGrant, PluginOwnedResource
from plugins.models.grant import MAX_PURGE_ERROR_LENGTH
from plugins.ownership.ownership_recorder import ownable_models

PURGE_ACTOR_TEMPLATE = "plugin {identifier} purge"
FAILED_ROW_RETRY_SECONDS = 3600
FAILED_ROW_CACHE_KEY = "plugins:purge:failed:{pk}"
# Ownable models with no recycle bin, other than files: purged after the files and
# collections and before key-value tables and secrets, configurations before the models they
# use (an LLM or embedding model that a config still uses cannot be deleted), and venvs after
# the tools and flows whose code runs in them and before the custom libraries they name (the
# sandbox refuses to delete a library a venv still names).
EXTRA_PURGE_ORDER: tuple[str, ...] = (
    "ai_models.LLMConfig",
    "ai_models.EmbeddingConfig",
    "tables.RealtimeConfig",
    "tables.RealtimeTranscriptionConfig",
    "tables.OpenAIRealtimeConfig",
    "tables.ElevenLabsRealtimeConfig",
    "tables.GeminiRealtimeConfig",
    "ai_models.LLMModel",
    "ai_models.EmbeddingModel",
    "tables.RealtimeModel",
    "tables.RealtimeTranscriptionModel",
    "proxies.SandboxVenvBinding",
    "proxies.SandboxCustomLibraryBinding",
)
# Ownable roots that bind a resource the sandbox holds: the service that pairs the two
# deletes both, as a person's delete through the gateway does.
PROXIED_ROOT_SERVICES: Mapping[str, type[VenvService | CustomLibraryService]] = MappingProxyType(
    {
        "proxies.SandboxVenvBinding": VenvService,
        "proxies.SandboxCustomLibraryBinding": CustomLibraryService,
    }
)
# Model rows and the configurations that use them; the configurations RESTRICT the rows.
_CONFIGS_OF_MODEL = {
    "ai_models.LLMModel": "ai_models.LLMConfig",
    "ai_models.EmbeddingModel": "ai_models.EmbeddingConfig",
}
_OPEN_SESSION_STATES = (
    Session.SessionStatus.PENDING,
    Session.SessionStatus.RUN,
    Session.SessionStatus.WAIT_FOR_USER,
)


@cache
def owned_purge_order() -> tuple[type[Model], ...]:
    """Every ownable model, in the order the purger deletes them: the recycle bin's
    `EMPTY_ORDER`, with `EXTRA_PURGE_ORDER` just before key-value tables."""
    resources = bin_resources()
    order: list[type[Model]] = []
    for source in EMPTY_ORDER:
        if source == RecycleBinSource.KEY_VALUE_TABLE:
            order.extend(apps.get_model(label) for label in EXTRA_PURGE_ORDER)
        order.append(StorageFile if source == RecycleBinSource.STORAGE else resources[source].model)
    return tuple(order)


@dataclass(frozen=True)
class PurgePassResult:
    """What one pass did.

    Attributes:
        held_back: Rows the pass did not try because one failed within the last hour; their
            error stands until a pass gets through them.
        remaining: Ownership rows still left once the pass ended: rows it did not reach,
            rows another process held, flows with a running session, venvs and custom
            libraries still in use, and failed rows.
        first_error: `"<model> <pk>: <message>"` of the first failed row, at most 2000
            characters; None when no row failed.
        truncated: The pass stopped at its deadline before it went through every row, so a
            row it never reached may be one that failed before.
    """

    purged: int
    failed: int
    remaining: int
    first_error: str | None
    held_back: int = 0
    truncated: bool = False


@dataclass(frozen=True)
class HandedOver:
    """The plugin's venvs and custom libraries the organization now owns, each as
    `"<name> (id <n>)"` with the id the gateway answers to; `"id <n>"` when the sandbox
    no longer knows its name."""

    venvs: tuple[str, ...] = ()
    custom_libraries: tuple[str, ...] = ()


@dataclass(frozen=True)
class HandOverPlan:
    """What `plan_hand_over` read outside the lock, for `hand_over` to check and apply.

    Attributes:
        row_ids: The ownership rows left when it was read, in pk order; `hand_over` does
            nothing unless exactly these are left.
    """

    organization_id: int
    plugin_identifier: str
    grant: PluginGrant | None
    row_ids: tuple[int, ...] = ()
    venv_ids: tuple[int, ...] = ()
    library_ids: tuple[int, ...] = ()
    handed_over: HandedOver = HandedOver()


class _Outcome(Enum):
    PURGED = auto()
    WAITING = auto()
    FAILED = auto()
    ORGANIZATION_GONE = auto()


class OwnedResourcePurger:
    def purge(
        self,
        *,
        organization_id: int,
        plugin_identifier: str,
        grant: PluginGrant | None,
        until: float,
    ) -> PurgePassResult:
        """Delete the rows the plugin owns in the organization, in `owned_purge_order()`.

        With `grant`, the rows owned under it and the rows of the organization and plugin
        whose grant is gone; without, only the latter. Stops once `until` (a
        `time.monotonic()` deadline) has passed, after at least one row. Never raises: a row
        that fails, a delete reaching another organization included, is logged, counted and
        left alone for an hour. Stops at once when the organization has been deleted, which
        took everything with it.
        """
        targets = purge_targets(organization_id, plugin_identifier, grant)
        actor = PURGE_ACTOR_TEMPLATE.format(identifier=plugin_identifier)
        library_usage = _CustomLibraryUsage.read(targets, organization_id, plugin_identifier)
        purged = failed = held_back = 0
        first_error = None
        attempted = 0
        truncated = False
        for row_pk in _in_purge_order(targets):
            if attempted and time.monotonic() >= until:
                truncated = True
                break
            if shared_cache.get(FAILED_ROW_CACHE_KEY.format(pk=row_pk)) is not None:
                held_back += 1
                continue
            attempted += 1
            outcome, error = self._purge_row(
                row_pk, organization_id, plugin_identifier, actor, library_usage
            )
            if outcome == _Outcome.ORGANIZATION_GONE:
                break
            if outcome == _Outcome.PURGED:
                purged += 1
            elif outcome == _Outcome.FAILED:
                failed += 1
                first_error = first_error or error
        return PurgePassResult(
            purged=purged,
            failed=failed,
            remaining=targets.count(),
            first_error=first_error,
            held_back=held_back,
            truncated=truncated,
        )

    def _purge_row(
        self,
        row_pk: int,
        organization_id: int,
        identifier: str,
        actor: str,
        library_usage: "_CustomLibraryUsage",
    ) -> tuple[_Outcome, str | None]:
        model = None
        object_id = None
        try:
            with transaction.atomic():
                # The lock storage writes take first, so a purge never interleaves with an
                # upload, a restore or the organization's deletion. Not a key lock: rows that
                # point at the organization (a person saving a flow there) go on meanwhile.
                if (
                    Organization.objects.select_for_update(no_key=True)
                    .filter(pk=organization_id)
                    .first()
                    is None
                ):
                    return _Outcome.ORGANIZATION_GONE, None
                row = (
                    PluginOwnedResource.objects.select_for_update(skip_locked=True)
                    .filter(pk=row_pk)
                    .first()
                )
                if row is None:
                    return _Outcome.WAITING, None
                model = ContentType.objects.get_for_id(row.content_type_id).model_class()
                object_id = row.object_id
                if model is None or model not in ownable_models():
                    # A model gone from the code: nothing of it can be run or purged.
                    row.delete()
                    return _Outcome.PURGED, None
                root = (
                    _manager(model)
                    .select_for_update()
                    .filter(pk=object_id, org_id=organization_id)
                    .first()
                )
                if root is None and _manager(model).filter(pk=object_id).exists():
                    # An ownership row naming another organization's resource: never
                    # deleted from here, and the row is dropped.
                    logger.warning(
                        "plugins.purge.foreign_root plugin={plugin} org={org} model={model} pk={pk}",
                        plugin=identifier,
                        org=organization_id,
                        model=model._meta.label,
                        pk=object_id,
                    )
                if root is not None and _used_by_configs_the_plugin_does_not_own(root, identifier):
                    # Kept: the organization's later configs reuse a custom model row the
                    # plugin added (`CatalogModelResolver`), and RESTRICT keeps it while they
                    # use it. Only the plugin's ownership of it ends.
                    logger.info(
                        "plugins.purge.ownership_released plugin={plugin} org={org} model={model} "
                        "pk={pk}",
                        plugin=identifier,
                        org=organization_id,
                        model=model._meta.label,
                        pk=object_id,
                    )
                    row.delete()
                    return _Outcome.PURGED, None
                if root is not None and not _delete_root(
                    root, organization_id, actor, library_usage
                ):
                    return _Outcome.WAITING, None
                row.delete()
                return _Outcome.PURGED, None
        except Exception as error:  # never raised: one row must not stop the purge of the rest
            shared_cache.set(FAILED_ROW_CACHE_KEY.format(pk=row_pk), 1, FAILED_ROW_RETRY_SECONDS)
            label = model._meta.label if model is not None else "unknown"
            logger.warning(
                "plugins.purge.resource_failed plugin={plugin} org={org} model={model} pk={pk} "
                "error={error}",
                plugin=identifier,
                org=organization_id,
                model=label,
                pk=object_id,
                error=type(error).__name__,
            )
            return _Outcome.FAILED, _error_text(model, object_id, error)

    def plan_hand_over(
        self, *, organization_id: int, plugin_identifier: str, grant: PluginGrant | None
    ) -> HandOverPlan | None:
        """Read, without a lock, which of the plugin's venvs and custom libraries the
        organization would get now; outside any transaction, as it asks the sandbox.

        Everything `purge_targets` still names must be a venv that code some tool or node owns
        runs in, or a custom library some venv of the organization names. None while anything
        else is left, or one of them is not in use: a later pass deals with it. Asks nothing of
        the sandbox when a row of another kind is left; else it asks for the organization's
        venvs once, and for the libraries' names once when a library is left.

        Raises:
            ClientError: The sandbox could not be asked. Nothing is handed over.
        """
        targets = purge_targets(organization_id, plugin_identifier, grant)
        venv_type, library_type = _binding_content_type_ids()
        if targets.exclude(content_type_id__in=[venv_type, library_type]).exists():
            return None
        rows = list(targets.order_by("pk").values_list("pk", "content_type_id", "object_id"))
        if not rows:
            return HandOverPlan(organization_id, plugin_identifier, grant)
        if any(kind not in (venv_type, library_type) for _pk, kind, _object_id in rows):
            # Added since the check above, which only spares reading every row.
            return None
        venv_ids = sorted({object_id for _pk, kind, object_id in rows if kind == venv_type})
        library_ids = sorted({object_id for _pk, kind, object_id in rows if kind == library_type})
        venv_count = SandboxVenvBinding.objects.filter(
            pk__in=venv_ids, org_id=organization_id
        ).count()
        libraries = list(
            SandboxCustomLibraryBinding.objects.filter(
                pk__in=library_ids, org_id=organization_id
            ).order_by("pk")
        )
        if venv_count != len(venv_ids) or len(libraries) != len(library_ids):
            # Gone, or another organization's: the pass drops such a row.
            return None
        if not _all_run_owned_code(venv_ids):
            return None
        organization_venvs = _organization_venvs(organization_id)
        named = _named_custom_libraries(organization_venvs)
        library_names = _custom_library_names(libraries)
        if any(
            library_names.get(library.pk) is None
            or canonicalize_name(library_names[library.pk]) not in named
            for library in libraries
        ):
            return None
        venv_names = {binding.pk: venv.get("name") for venv, binding in organization_venvs}
        return HandOverPlan(
            organization_id,
            plugin_identifier,
            grant,
            row_ids=tuple(pk for pk, _kind, _object_id in rows),
            venv_ids=tuple(venv_ids),
            library_ids=tuple(library_ids),
            handed_over=HandedOver(
                venvs=tuple(_hand_over_label(venv_names.get(pk), pk) for pk in venv_ids),
                custom_libraries=tuple(
                    _hand_over_label(library_names[pk], pk) for pk in library_ids
                ),
            ),
        )

    def hand_over(self, plan: HandOverPlan) -> HandedOver | None:
        """Give the organization what `plan` found, in the caller's transaction; no network.

        Locks the ownership rows and the bindings, and checks again what this database can
        tell: exactly the plan's rows are left, the bindings are still the organization's, and
        code some tool or node owns still runs in each venv. Their ownership rows then go and
        the resources stay as they are, the libraries the plugin chose for a venv with it.
        None, with nothing changed, when any of that changed since the plan or another process
        holds a row: a later pass plans again. Which libraries a venv names only the sandbox
        can tell, so that stays as the plan read it. Code no tool or node owns does not keep a
        venv: creators insert code in one transaction with its owner, so such code never gets
        one.
        """
        targets = purge_targets(plan.organization_id, plan.plugin_identifier, plan.grant)
        row_ids = tuple(
            targets.select_for_update(skip_locked=True).order_by("pk").values_list("pk", flat=True)
        )
        if row_ids != plan.row_ids or targets.count() != len(row_ids):
            return None
        if not row_ids:
            return HandedOver()
        if (
            _locked_bindings(SandboxVenvBinding, plan.venv_ids, plan.organization_id) is None
            or _locked_bindings(SandboxCustomLibraryBinding, plan.library_ids, plan.organization_id)
            is None
            or not _all_run_owned_code(plan.venv_ids)
        ):
            return None
        PluginOwnedResource.objects.filter(pk__in=row_ids).delete()
        for model, ids in (
            (SandboxVenvBinding, plan.venv_ids),
            (SandboxCustomLibraryBinding, plan.library_ids),
        ):
            for pk in ids:
                logger.info(
                    "plugins.purge.handed_over plugin={plugin} org={org} model={model} pk={pk}",
                    plugin=plan.plugin_identifier,
                    org=plan.organization_id,
                    model=model._meta.label,
                    pk=pk,
                )
        return plan.handed_over


def purge_targets(
    organization_id: int, identifier: str, grant: PluginGrant | None
) -> QuerySet[PluginOwnedResource]:
    """The ownership rows a purge of `grant` deletes: its own and the organization's rows of the
    plugin whose grant is gone; only the latter without a grant."""
    orphaned = Q(org_id=organization_id, plugin_identifier=identifier, grant__isnull=True)
    if grant is None:
        return PluginOwnedResource.objects.filter(orphaned)
    return PluginOwnedResource.objects.filter(Q(grant=grant) | orphaned)


def _in_purge_order(targets: QuerySet[PluginOwnedResource]) -> Iterable[int]:
    """The rows' pks in `owned_purge_order()`, oldest first within a model; one query (content
    types are cached per process). A row of a model outside the order comes last."""
    order = owned_purge_order()
    content_types = ContentType.objects.get_for_models(*order)
    ranks = {content_types[model].pk: rank for rank, model in enumerate(order)}
    rows = targets.order_by().values_list("pk", "content_type_id")
    return [pk for pk, _ in sorted(rows, key=lambda row: (ranks.get(row[1], len(ranks)), row[0]))]


def _manager(model: type[Model]):
    """Every row of the model, binned ones included."""
    return getattr(model, "all_objects", None) or model._default_manager


def _used_by_configs_the_plugin_does_not_own(root: Model, identifier: str) -> bool:
    """Whether `root` is a model row a configuration the plugin does not own still uses."""
    config_label = _CONFIGS_OF_MODEL.get(type(root)._meta.label)
    if config_label is None:
        return False
    config_model = apps.get_model(config_label)
    plugin_configs = PluginOwnedResource.objects.filter(
        plugin_identifier=identifier,
        content_type=ContentType.objects.get_for_model(config_model),
    ).values("object_id")
    return _manager(config_model).filter(model_id=root.pk).exclude(pk__in=plugin_configs).exists()


def _locked_bindings(
    model: type[SandboxVenvBinding | SandboxCustomLibraryBinding],
    ids: Iterable[int],
    organization_id: int,
) -> list | None:
    """The organization's bindings of `ids`, locked, in pk order; None when one is missing."""
    ids = set(ids)
    bindings = list(
        model.objects.select_for_update().filter(pk__in=ids, org_id=organization_id).order_by("pk")
    )
    return bindings if len(bindings) == len(ids) else None


def _binding_content_type_ids() -> tuple[int, int]:
    """The content type ids of venv and custom library bindings; cached per process."""
    content_types = ContentType.objects.get_for_models(
        SandboxVenvBinding, SandboxCustomLibraryBinding
    )
    return content_types[SandboxVenvBinding].pk, content_types[SandboxCustomLibraryBinding].pk


def _owned_code() -> QuerySet[PythonCode]:
    """Python code some tool or node owns, binned ones included: what a person can open, move
    or delete. Code no owner has left runs nowhere."""
    return PythonCode.objects.filter(PythonCodeCleanupService.owned_by_any_owner())


def _all_run_owned_code(venv_ids: Iterable[int]) -> bool:
    venv_ids = set(venv_ids)
    in_use = set(
        _owned_code().filter(venv_id__in=venv_ids).values_list("venv_id", flat=True).distinct()
    )
    return in_use == venv_ids


@dataclass(frozen=True)
class _CustomLibraryUsage:
    """Which venvs of the organization name which of the plugin's custom libraries, read from
    the sandbox once per pass, before any row's transaction.

    Attributes:
        readable: False when the sandbox could not be asked; every library then waits.
        library_ids: The library bindings read; one added later waits for the next pass.
        library_names: Their names by binding pk; a library the sandbox no longer has is
            left out.
        named_by_venv: The canonical custom library names each venv installs, by venv
            binding pk.
    """

    readable: bool = True
    library_ids: frozenset[int] = frozenset()
    library_names: Mapping[int, str] = MappingProxyType({})
    named_by_venv: Mapping[int, frozenset[str]] = MappingProxyType({})

    @classmethod
    def read(
        cls, targets: QuerySet[PluginOwnedResource], organization_id: int, identifier: str
    ) -> "_CustomLibraryUsage":
        """Read it outside any transaction; asks nothing when no library is left.

        A sandbox outage is logged, not raised: the pass goes on with every other row, and
        no library is deleted on the assumption that nothing uses it.
        """
        _venv_type, library_type = _binding_content_type_ids()
        libraries = list(
            SandboxCustomLibraryBinding.objects.filter(
                pk__in=targets.filter(content_type_id=library_type).values("object_id"),
                org_id=organization_id,
            ).order_by("pk")
        )
        if not libraries:
            return cls()
        try:
            library_names = _custom_library_names(libraries)
            venvs = _organization_venvs(organization_id)
        except ClientError as error:
            logger.warning(
                "plugins.purge.library_usage_unreadable plugin={plugin} org={org} error={error}",
                plugin=identifier,
                org=organization_id,
                error=type(error).__name__,
            )
            return cls(readable=False)
        return cls(
            library_ids=frozenset(library.pk for library in libraries),
            library_names=MappingProxyType(library_names),
            named_by_venv=MappingProxyType(
                {
                    binding.pk: frozenset(_named_custom_libraries([(venv, binding)]))
                    for venv, binding in venvs
                }
            ),
        )

    def in_use(self, library: SandboxCustomLibraryBinding, organization_id: int) -> bool:
        """Whether some venv of the organization still names `library` (the sandbox's 409).

        Only the database is asked: a venv the pass deleted since the read names nothing any
        more. A venv created since then is not seen; the sandbox refuses that delete, and the
        row fails and is tried again in a later pass.
        """
        if not self.readable or library.pk not in self.library_ids:
            return True
        name = self.library_names.get(library.pk)
        if name is None:
            # The sandbox no longer has it: the delete drops the binding.
            return False
        remaining_venvs = SandboxVenvBinding.objects.filter(
            pk__in=self.named_by_venv, org_id=organization_id
        ).values_list("pk", flat=True)
        return any(
            canonicalize_name(name) in self.named_by_venv[venv_pk] for venv_pk in remaining_venvs
        )


def _organization_venvs(organization_id: int) -> list[tuple[dict, SandboxVenvBinding]]:
    """Every venv of the organization as the sandbox lists it, with its binding; one call."""
    _page, pairs = VenvService().list_page(
        SandboxVenvBinding.objects.filter(org_id=organization_id)
    )
    return pairs


def _named_custom_libraries(venvs: list[tuple[dict, SandboxVenvBinding]]) -> set[str]:
    """The canonical names of the custom libraries `venvs` install.

    The sandbox refuses to delete a library of the organization's scope while a venv there
    lists it marked custom; an entry without the mark is a package index lookup. Names are
    compared canonical, so a spelling the sandbox would not match keeps a library rather than
    deleting one a venv needs.
    """
    return {
        canonicalize_name(entry["name"])
        for venv, _binding in venvs
        for entry in venv.get("libs") or []
        if isinstance(entry, dict) and entry.get("is_custom") and entry.get("name")
    }


def _custom_library_names(libraries: list[SandboxCustomLibraryBinding]) -> dict[int, str]:
    """The names the sandbox stores for `libraries`, by binding pk; one call. A library the
    sandbox no longer has is left out."""
    if not libraries:
        return {}
    _page, pairs = CustomLibraryService().list_page(
        SandboxCustomLibraryBinding.objects.filter(pk__in=[library.pk for library in libraries])
    )
    return {binding.pk: library["name"] for library, binding in pairs if library.get("name")}


def _hand_over_label(name: str | None, pk: int) -> str:
    return f"{name} (id {pk})" if name else f"id {pk}"


def _delete_root(
    root: Model, organization_id: int, actor: str, library_usage: _CustomLibraryUsage
) -> bool:
    """Delete `root` (locked) for good; False when it must wait for a later pass.

    A venv waits while code some tool or node owns runs in it, a custom library while
    `library_usage` finds a venv naming it. Code no tool or node owns is deleted with its
    venv: every creator of code inserts it in one transaction with its owner, so code
    without an owner is never one about to get one.
    """
    model = type(root)
    if model is StorageFile:
        _purge_file(root, organization_id, actor)
        return True
    proxied_service = PROXIED_ROOT_SERVICES.get(model._meta.label)
    if proxied_service is not None:
        # A venv or library still in use waits for the plugin's own code or venvs to go;
        # what still uses it once nothing else is left is the organization's (`hand_over`).
        if isinstance(root, SandboxVenvBinding):
            if _owned_code().filter(venv=root).exists():
                return False
            # Code no tool or node owns any more still PROTECTs the venv, yet runs nowhere,
            # and nothing else reclaims it: it goes as its last owner's delete takes it.
            PythonCodeCleanupService.delete_orphaned(root.python_codes.values_list("pk", flat=True))
        elif library_usage.in_use(root, organization_id):
            return False
        _delete_proxied(root, proxied_service(), actor)
        return True
    if model in {resource.model for resource in bin_resources().values()}:
        if model is Graph and _has_open_session(root):
            return False
        if root.soft_deleted_at is None:
            move_to_recycle_bin(root, None)
        binned = model.deleted_objects.select_for_update().get(pk=root.pk)
        PurgeService.purge(binned, actor=actor)
        return True
    _hard_delete(root, actor)
    return True


def _has_open_session(graph: Graph) -> bool:
    return Session.objects.filter(graph_id=graph.pk, status__in=_OPEN_SESSION_STATES).exists()


def _purge_file(file: StorageFile, organization_id: int, actor: str) -> None:
    """Bin a live file through storage, then purge it from the bin.

    A file binned together with its folder is not an entry of the bin on its own, and the
    folder is the organization's: only the file's row and its trashed object are deleted.
    """
    manager = get_storage_manager()
    if file.soft_deleted_at is None:
        manager.delete(organization_id, file.path, user=None)
        file = StorageFile.all_objects.select_for_update().get(pk=file.pk)
    bin_service = StorageRecycleBinService(manager)
    if StorageRecycleBinService.top_level(organization_id).filter(pk=file.pk).exists():
        bin_service.purge(organization_id, file.pk, actor=actor)
        return
    using = router.db_for_write(StorageFile)
    rows = StorageFile.all_objects.using(using).filter(pk=file.pk)
    collector = Collector(using=using, origin=rows)
    collector.collect(rows)
    CascadeOrgGuard(organization_id, f"storage entry {file.pk}", using).check_collected(collector)
    collector.delete()
    manager.delete_trash_path(organization_id, file.soft_delete_batch, file.path)
    logger.info(
        "Purged storage file {pk} of org {org_id} (batch {batch}) by {actor}",
        pk=file.pk,
        org_id=organization_id,
        batch=file.soft_delete_batch,
        actor=actor,
    )


def _delete_proxied(
    binding: Model, service: VenvService | CustomLibraryService, actor: str
) -> None:
    """Delete the sandbox's venv or custom library (its wheels with it), then its binding.

    Runs in the row's transaction, under the organization's lock, sandbox calls included: the
    binding goes only where its resource was removed, and the `ClientNotFoundError` branch
    relies on that. A hanging sandbox holds the lock for up to the client's timeout per call.

    Reached once nothing this side can see uses it. What can still refuse it is what this
    side cannot see, such as a venv of the organization's scope with no binding naming the
    library (the sandbox's 409). The row then fails and is tried again in a later pass.
    """
    pk = binding.pk
    organization_id = binding.org_id
    try:
        service.delete(binding)
    except ClientNotFoundError:
        # The sandbox no longer has it: an earlier pass removed it and then rolled back.
        binding.delete()
    logger.info(
        "Purged {model} {pk} of org {org_id} by {actor}",
        model=type(binding).__name__,
        pk=pk,
        org_id=organization_id,
        actor=actor,
    )


def _hard_delete(root: Model, actor: str) -> None:
    """Delete a root that has no recycle bin, refused when its cascade reaches another
    organization's row."""
    using = router.db_for_write(type(root))
    collector = Collector(using=using, origin=root)
    collector.collect([root])
    CascadeOrgGuard.for_root(root, using).check_collected(collector)
    pk = root.pk
    organization_id = root.org_id
    collector.delete()
    logger.info(
        "Purged {model} {pk} of org {org_id} by {actor}",
        model=type(root).__name__,
        pk=pk,
        org_id=organization_id,
        actor=actor,
    )


def _error_text(model: type[Model] | None, object_id: int | None, error: Exception) -> str:
    """What the SuperAdmin reads about a failed row. Only EpicStaff's own errors keep their
    message, which never names another organization's data; any other error is named by its
    class alone, as in the log."""
    name = model._meta.verbose_name.capitalize() if model is not None else "Resource"
    message = str(error.detail) if isinstance(error, CustomAPIExeption) else type(error).__name__
    return f"{name} {object_id}: {message}"[:MAX_PURGE_ERROR_LENGTH]
