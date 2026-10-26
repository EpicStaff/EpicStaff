"""What deleting a grant's data, or a whole plugin, would remove, read before confirming.

The grant preview lists the organization's flows that use what the plugin owns with the
suspend preview's pieces, so the two dialogs agree on which flows are affected. The plugin
preview also backs the uninstall dialog. Both are read-only, allowed in every state, and
their queries do not depend on how many flows, grants or owned rows there are. The phrase
they show is the server's (`purge_phrases`).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from django.db.models.functions import Lower
from django.utils import timezone

from plugins.configuration.grace_period import grace_period
from plugins.exceptions import GrantNotFoundError, PluginNotFoundError
from plugins.lifecycle.org_removed_hooks import (
    UNFINISHED_ORG_REMOVED_STATES,
    has_org_removed_hook,
)
from plugins.lifecycle.purge_phrases import grant_purge_phrase, plugin_purge_phrase
from plugins.lifecycle.suspend_preview_service import (
    PREVIEW_LIST_LIMIT,
    PreviewDefaultModel,
    PreviewList,
    affected_default_models,
    affected_flows,
    limited,
    running_sessions,
    split_flows,
)
from plugins.models import (
    HookJobKind,
    Plugin,
    PluginDatabase,
    PluginGrant,
    PluginHookJob,
    PluginOwnedResource,
    PluginState,
)
from plugins.ownership.existing_owned import owned_resource_counts_by_grant
from plugins.ownership.owned_resource_summary import owned_resource_summary, summarize_owned
from plugins.runs.owned_resource_index import OwnedResourceIndex


class PluginDataFate(StrEnum):
    """What happens to the plugin's own data for the organization."""

    # A backend with an organization removed hook: the plugin deletes it.
    DELETED_BY_PLUGIN = "deleted_by_plugin"
    # A backend without one: it stays where the plugin keeps it until the plugin is deleted.
    KEPT_UNTIL_PLUGIN_DELETED = "kept_until_plugin_deleted"
    # No backend: the plugin keeps no data of its own.
    NONE = "none"


@dataclass(frozen=True)
class GrantPurgePreview:
    grant: PluginGrant
    verification_phrase: str
    owned_resources: list[dict]
    organization_flows: PreviewList
    plugin_flows: PreviewList
    running_sessions: PreviewList
    default_models: list[PreviewDefaultModel]
    plugin_data: PluginDataFate


@dataclass(frozen=True)
class PurgeOrganization:
    grant_id: int
    organization_id: int
    organization_name: str
    state: str
    owned_resource_count: int


@dataclass(frozen=True)
class PurgeDatabase:
    name: str
    size_bytes: int | None


@dataclass(frozen=True)
class PluginPurgePreview:
    plugin: Plugin
    verification_phrase: str
    data_kept_until: datetime
    organizations: PreviewList
    owned_resources: list[dict]
    data_removals_open: int
    has_org_removed_hook: bool
    database: PurgeDatabase | None
    has_backend: bool
    has_spa: bool
    package_count: int


class PurgePreviewService:
    def grant_preview(self, identifier: str, grant_id: int) -> GrantPurgePreview:
        """What deleting a grant's data removes and affects; reads only, creates nothing.

        Raises:
            GrantNotFoundError: No such grant of this plugin.
        """
        grant = (
            PluginGrant.objects.select_related("plugin__current_package", "org")
            .defer("plugin__current_package__icon_bytes")
            .filter(pk=grant_id, plugin__identifier=identifier)
            .first()
        )
        if grant is None:
            raise GrantNotFoundError()
        index = OwnedResourceIndex.for_grant(grant)
        flows = affected_flows(index, grant.org_id)
        organization_flows, plugin_flows = split_flows(index, flows)
        return GrantPurgePreview(
            grant=grant,
            verification_phrase=grant_purge_phrase(identifier, grant.org.name),
            owned_resources=owned_resource_summary(grant),
            organization_flows=limited(organization_flows),
            plugin_flows=limited(plugin_flows),
            running_sessions=running_sessions(flows),
            default_models=affected_default_models(index, grant.org_id),
            plugin_data=plugin_data_fate(grant.plugin),
        )

    def plugin_preview(self, identifier: str) -> PluginPurgePreview:
        """What uninstalling or deleting the plugin affects; reads only, creates nothing.

        Raises:
            PluginNotFoundError: No such plugin.
        """
        plugin = (
            Plugin.objects.select_related("current_package")
            .defer("current_package__icon_bytes")
            .filter(identifier=identifier)
            .first()
        )
        if plugin is None:
            raise PluginNotFoundError()
        manifest = plugin.current_package.parsed_manifest if plugin.current_package else None
        database = (
            PluginDatabase.objects.filter(plugin=plugin)
            .values_list("database_name", "size_bytes")
            .first()
        )
        return PluginPurgePreview(
            plugin=plugin,
            verification_phrase=plugin_purge_phrase(identifier),
            data_kept_until=(
                plugin.purge_after
                if plugin.state == PluginState.UNINSTALLING and plugin.purge_after is not None
                else timezone.now() + grace_period()
            ),
            organizations=_organizations(plugin),
            owned_resources=summarize_owned(
                PluginOwnedResource.objects.filter(plugin_identifier=identifier)
            ),
            data_removals_open=PluginHookJob.objects.filter(
                plugin=plugin,
                kind=HookJobKind.ORG_REMOVED,
                state__in=UNFINISHED_ORG_REMOVED_STATES,
            ).count(),
            has_org_removed_hook=has_org_removed_hook(plugin),
            database=PurgeDatabase(*database) if database is not None else None,
            has_backend=manifest is not None and manifest.backend is not None,
            has_spa=manifest is not None and manifest.spa is not None,
            package_count=plugin.packages.count(),
        )


def plugin_data_fate(plugin: Plugin) -> PluginDataFate:
    """What happens to the plugin's own data when an organization's data is deleted."""
    manifest = plugin.current_package.parsed_manifest if plugin.current_package else None
    if manifest is None or manifest.backend is None:
        return PluginDataFate.NONE
    if has_org_removed_hook(plugin):
        return PluginDataFate.DELETED_BY_PLUGIN
    return PluginDataFate.KEPT_UNTIL_PLUGIN_DELETED


def _organizations(plugin: Plugin) -> PreviewList:
    """The plugin's grants by organization name, at most `PREVIEW_LIST_LIMIT`, each with how
    many existing resources the plugin owns there."""
    grants = PluginGrant.objects.filter(plugin=plugin)
    page = list(
        grants.order_by(Lower("org__name"), "pk").values_list("pk", "org_id", "org__name", "state")[
            :PREVIEW_LIST_LIMIT
        ]
    )
    counts = owned_resource_counts_by_grant(grant_id for grant_id, *_ in page)
    return PreviewList(
        total=grants.count(),
        items=[
            PurgeOrganization(
                grant_id=grant_id,
                organization_id=organization_id,
                organization_name=organization_name,
                state=state,
                owned_resource_count=counts.get(grant_id, 0),
            )
            for grant_id, organization_id, organization_name, state in page
        ],
    )
