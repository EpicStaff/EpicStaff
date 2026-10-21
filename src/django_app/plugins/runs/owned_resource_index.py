"""Which rows of a run a plugin owns: one matcher for the run guard, the suspend preview and
the session stopper, so all three agree on what a suspension stops.

A run uses an owned row when the row is one the run reaches (`RunResources.refs`), or when it
is a file under a storage folder the run reaches (`RunResources.storage_prefixes`).
"""

import operator
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

INACTIVE_GRANT_STATES = tuple(state for state in GrantState if state != GrantState.ACTIVE)
# Owned rows that refuse runs: their grant is not active, or gone.
_INACTIVE_Q = Q(grant__isnull=True) | Q(grant__state__in=INACTIVE_GRANT_STATES)
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
        self._owned_file_paths = owned_file_paths

    @classmethod
    def for_inactive_grants(
        cls, organization_id: int, resources: RunResources
    ) -> "OwnedResourceIndex":
        """The rows of `resources` the organization's non-active or removed grants own.

        One query for the rows the refs name, and one more for files under the storage
        folders when there are any; none when `resources` reaches no ownable row.
        """
        candidates = PluginOwnedResource.objects.filter(org_id=organization_id).filter(_INACTIVE_Q)
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
        return not self._owners_by_ref and not self._owned_file_paths

    def holds(self, model_label: str, pk: int) -> bool:
        """Whether the index holds the row `model_label` `pk`."""
        return ResourceRef(model_label=model_label, pk=pk) in self._owners_by_ref

    def first_owner(self, resources: RunResources) -> BlockingOwner | None:
        """The owner of a row `resources` uses, the lowest plugin identifier first; None if none."""
        owners = [self._owners_by_ref[ref] for ref in resources.refs if ref in self._owners_by_ref]
        if resources.storage_prefixes:
            prefixes = tuple(resources.storage_prefixes)
            owners.extend(
                owner for path, owner in self._owned_file_paths if path.startswith(prefixes)
            )
        return min(
            owners, key=lambda owner: (owner.plugin_identifier, owner.grant_id or 0), default=None
        )


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
    owners: dict[tuple, BlockingOwner] = {}
    by_ref = {}
    for content_type_id, object_id, *owner_fields in _with_owner(owned).values_list(
        "content_type_id", "object_id", *_OWNER_FIELDS
    ):
        label = ContentType.objects.get_for_id(content_type_id).model_class()._meta.label
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
