"""Which rows of a run a plugin owns: one matcher for the run guard, the suspend preview and
the session stopper, so all three agree on what a suspension stops.

A run uses an owned row when the row is one the run reaches (`RunResources.refs`), or when it
is a file under a storage folder the run reaches (`RunResources.storage_prefixes`).
"""

import operator
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from functools import reduce

from django.contrib.contenttypes.models import ContentType
from django.db.models import F, OuterRef, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce
from tables.models import StorageFile
from tables.services.run_resources import ResourceRef, RunResources

from plugins.models import GrantState, Plugin, PluginGrant, PluginOwnedResource
from plugins.ownership.ownership_recorder import ownable_models

# A run that uses a row owned under a grant in one of these states is refused.
INACTIVE_GRANT_STATES = tuple(state for state in GrantState if state != GrantState.ACTIVE)
# A session already running that uses such a row is stopped, except while the organization is
# upgraded: an upgrade refuses new runs and lets running sessions finish.
RUN_STOPPING_GRANT_STATES = tuple(
    state
    for state in INACTIVE_GRANT_STATES
    if state not in (GrantState.UPGRADING, GrantState.UPGRADE_FAILED)
)
_OWNER_FIELDS = (
    "plugin_identifier",
    "grant_id",
    "grant__state",
    "grant__suspended_at",
    "grant__updated_at",
    "plugin_name",
)


@dataclass(frozen=True)
class BlockingOwner:
    """The plugin owning a row a run would use, and the state of its grant.

    Attributes:
        grant_state: None once the grant is gone.
        since: When the grant was suspended, else when it last changed; None once it is gone.
    """

    plugin_identifier: str
    plugin_name: str
    grant_id: int | None
    grant_state: str | None
    since: datetime | None


class OwnedResourceIndex:
    """Owned rows of an organization, loaded once and matched against many runs in memory."""

    def __init__(
        self,
        owners_by_ref: dict[ResourceRef, BlockingOwner],
        owned_file_paths: list[tuple[str, BlockingOwner]],
    ):
        self._owners_by_ref = owners_by_ref
        # Each owner's paths sorted: whether it owns a file under a prefix is one binary
        # search, however many files the folder holds.
        paths_by_owner: dict[BlockingOwner, list[str]] = defaultdict(list)
        for path, owner in owned_file_paths:
            paths_by_owner[owner].append(path)
        self._paths_by_owner = {owner: sorted(paths) for owner, paths in paths_by_owner.items()}

    @classmethod
    def for_inactive_grants(
        cls,
        organization_id: int,
        resources: RunResources,
        *,
        grant_states: tuple[str, ...] = INACTIVE_GRANT_STATES,
    ) -> "OwnedResourceIndex":
        """The rows of `resources` the organization's removed grants own, or its grants in
        `grant_states` (every state but `active` by default).

        One query for the rows the refs name, and one more for files under the storage
        folders when there are any; none when `resources` reaches no ownable row.
        """
        candidates = PluginOwnedResource.objects.filter(org_id=organization_id).filter(
            Q(grant__isnull=True) | Q(grant__state__in=grant_states)
        )
        ownable_labels = _ownable_labels()
        pks_by_label: dict[str, list[int]] = {}
        for ref in resources.refs:
            if ref.model_label in ownable_labels:
                pks_by_label.setdefault(ref.model_label, []).append(ref.pk)
        owners_by_ref = {}
        if pks_by_label:
            content_types = _content_type_ids(pks_by_label)
            named = reduce(
                operator.or_,
                (
                    Q(content_type_id=content_types[label], object_id__in=pks)
                    for label, pks in pks_by_label.items()
                ),
            )
            owners_by_ref = _owners_by_ref(candidates.filter(named))
        owned_file_paths = (
            _owned_file_paths(candidates, resources.storage_prefixes)
            if resources.storage_prefixes
            else []
        )
        return cls(owners_by_ref, owned_file_paths)

    @classmethod
    def for_grant(cls, grant: PluginGrant) -> "OwnedResourceIndex":
        """Every row owned under `grant`, whatever its state: two queries."""
        owned = PluginOwnedResource.objects.filter(grant=grant)
        return cls(_owners_by_ref(owned), _owned_file_paths(owned, None))

    @property
    def is_empty(self) -> bool:
        return not self._owners_by_ref and not self._paths_by_owner

    def holds(self, model_label: str, pk: int) -> bool:
        """Whether the index holds the row `model_label` `pk`."""
        return ResourceRef(model_label=model_label, pk=pk) in self._owners_by_ref

    def first_owner(self, resources: RunResources) -> BlockingOwner | None:
        """The owner of a row `resources` uses, the lowest plugin identifier first; None if none."""
        owners = [self._owners_by_ref[ref] for ref in resources.refs if ref in self._owners_by_ref]
        for prefix in resources.storage_prefixes:
            owners.extend(
                owner
                for owner, paths in self._paths_by_owner.items()
                if _has_path_under(paths, prefix)
            )
        return min(
            owners, key=lambda owner: (owner.plugin_identifier, owner.grant_id or 0), default=None
        )


def _has_path_under(sorted_paths: list[str], prefix: str) -> bool:
    # The paths under a prefix sort right after it, so the first path not below the prefix
    # is under it if any is.
    index = bisect_left(sorted_paths, prefix)
    return index < len(sorted_paths) and sorted_paths[index].startswith(prefix)


def _ownable_labels() -> frozenset[str]:
    return frozenset(model._meta.label for model in ownable_models())


def _content_type_ids(labels) -> dict[str, int]:
    models_by_label = {model._meta.label: model for model in ownable_models()}
    content_types = ContentType.objects.get_for_models(
        *(models_by_label[label] for label in labels)
    )
    return {model._meta.label: content_type.pk for model, content_type in content_types.items()}


def _with_owner(owned: QuerySet) -> QuerySet:
    """The rows with what names their owner; the plugin's name falls back to its identifier
    once the plugin row is gone."""
    plugin_name = Subquery(
        Plugin.objects.filter(identifier=OuterRef("plugin_identifier")).values("name")[:1]
    )
    return owned.annotate(plugin_name=Coalesce(plugin_name, F("plugin_identifier")))


def _owners_by_ref(owned: QuerySet) -> dict[ResourceRef, BlockingOwner]:
    """The owner of each owned row, by the row it names. A row of a content type whose model
    is gone from the code is skipped: no run can reach it."""
    owners: dict[tuple, BlockingOwner] = {}
    labels: dict[int, str | None] = {}
    by_ref = {}
    for content_type_id, object_id, *owner_fields in _with_owner(owned).values_list(
        "content_type_id", "object_id", *_OWNER_FIELDS
    ):
        if content_type_id not in labels:
            model = ContentType.objects.get_for_id(content_type_id).model_class()
            labels[content_type_id] = model._meta.label if model is not None else None
        label = labels[content_type_id]
        if label is not None:
            by_ref[ResourceRef(model_label=label, pk=object_id)] = _owner(owners, owner_fields)
    return by_ref


def _owned_file_paths(owned: QuerySet, prefixes) -> list[tuple[str, BlockingOwner]]:
    """Paths of the live files among `owned`, only those under `prefixes` unless it is None."""
    files = (
        _with_owner(owned)
        .filter(content_type=ContentType.objects.get_for_model(StorageFile))
        .annotate(
            path=Subquery(StorageFile.objects.filter(pk=OuterRef("object_id")).values("path")[:1])
        )
    )
    if prefixes is None:
        files = files.filter(path__isnull=False)
    else:
        files = files.filter(
            reduce(operator.or_, (Q(path__startswith=prefix) for prefix in prefixes))
        )
    owners: dict[tuple, BlockingOwner] = {}
    return [
        (path, _owner(owners, owner_fields))
        for path, *owner_fields in files.values_list("path", *_OWNER_FIELDS)
    ]


def _owner(owners: dict[tuple, BlockingOwner], owner_fields) -> BlockingOwner:
    """One `BlockingOwner` per plugin and grant, shared by all its rows."""
    identifier, grant_id, state, suspended_at, updated_at, plugin_name = owner_fields
    key = (identifier, grant_id)
    if key not in owners:
        owners[key] = BlockingOwner(
            plugin_identifier=identifier,
            plugin_name=plugin_name,
            grant_id=grant_id,
            grant_state=state,
            since=(suspended_at or updated_at) if grant_id is not None else None,
        )
    return owners[key]
