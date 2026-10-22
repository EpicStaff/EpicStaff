import base64

from django.db.models import Count
from drf_spectacular.utils import extend_schema_field
from epicstaff_plugin.contracts.manifest import PluginManifest
from rest_framework import serializers

from plugins.lifecycle.grant_actions import GrantAction, allowed_grant_actions
from plugins.lifecycle.open_upgrades import open_upgrade_of
from plugins.lifecycle.plugin_actions import (
    PluginActionFacts,
    PluginLifecycleAction,
    allowed_plugin_actions,
)
from plugins.lifecycle.plugin_purge_service import purge_progress
from plugins.models import (
    GrantState,
    Plugin,
    PluginDatabase,
    PluginGrant,
    PluginPackage,
    PluginState,
    PluginUpgrade,
    ReviewState,
    SignatureStatus,
    SuspensionCause,
    Trust,
)
from plugins.models.upgrade import OPEN_UPGRADE_STAGES
from plugins.origins import PluginOrigins
from plugins.packages.review import action_label, resource_label, review_warnings
from plugins.packages.upgrade_review import PackageUpgradeReview, review_upgrade
from plugins.serializers.common import UserRefSerializer
from plugins.serializers.purge import OrgRemovedJobSerializer, PluginPurgeProgressSerializer
from plugins.serializers.upgrade import (
    AccessGrowthSerializer,
    PluginUpgradeSerializer,
    UpgradeReviewSerializer,
    UpgradeSummarySerializer,
)


def icon_url(plugin: Plugin) -> str | None:
    """Public URL of a plugin's approved icon; the version busts browser caches on upgrade."""
    if plugin.current_package is None:
        return None
    return f"/api/plugin-public/{plugin.identifier}/icon/?v={plugin.current_package.version}"


def declared_access_rows(manifest: PluginManifest) -> list[dict]:
    """The manifest's `access`, as the review and the organization's service-account list show it."""
    return [
        {
            "resource_type": declaration.resource_type,
            "resource_label": resource_label(declaration.resource_type),
            "actions": list(declaration.actions),
            "reason": declaration.reason,
        }
        for declaration in manifest.access
    ]


def open_upgrade_from_summary(plugin: Plugin) -> PluginUpgrade | None:
    """The plugin's open upgrade, from `with_summary()`'s prefetch when it is there."""
    prefetched = getattr(plugin, "open_upgrades", None)
    if prefetched is None:
        return open_upgrade_of(plugin)
    return prefetched[0] if prefetched else None


def datetime_text(value) -> str | None:
    """A datetime as the API writes it, or None."""
    return serializers.DateTimeField().to_representation(value) if value is not None else None


class PackageUploadSerializer(serializers.Serializer):
    file = serializers.FileField(allow_empty_file=False)


class GrantCreateSerializer(serializers.Serializer):
    organization_id = serializers.IntegerField(min_value=1)


class UpgradeHookSerializer(serializers.Serializer):
    state = serializers.CharField()
    attempt = serializers.IntegerField()
    from_version = serializers.CharField(allow_null=True)
    next_attempt_at = serializers.DateTimeField(allow_null=True)
    started_at = serializers.DateTimeField(allow_null=True)
    finished_at = serializers.DateTimeField(allow_null=True)
    error = serializers.CharField(allow_null=True)


class PackageReviewSerializer(serializers.ModelSerializer):
    """Everything a SuperAdmin reviews before approving a package; for a newer package of an
    installed plugin, also the upgrade review (`plugins.packages.upgrade_review`)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._reviews: dict[int, PackageUpgradeReview | None] = {}

    plugin_identifier = serializers.CharField(source="plugin.identifier")
    name = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    publisher = serializers.SerializerMethodField()
    icon_data_url = serializers.SerializerMethodField()
    signature = serializers.CharField(source="signature_status")
    signer = serializers.SerializerMethodField()
    uploaded_by = UserRefSerializer(allow_null=True)
    approved_by = UserRefSerializer(allow_null=True)
    is_upgrade = serializers.SerializerMethodField()
    current_version = serializers.SerializerMethodField()
    contents = serializers.SerializerMethodField()
    access = serializers.SerializerMethodField()
    user_permissions = serializers.SerializerMethodField()
    public_paths = serializers.SerializerMethodField()
    outbound_hosts = serializers.SerializerMethodField()
    settings = serializers.SerializerMethodField()
    limits = serializers.SerializerMethodField()
    hooks = serializers.SerializerMethodField()
    warnings = serializers.SerializerMethodField()
    access_growth = serializers.SerializerMethodField()
    upgrade = serializers.SerializerMethodField()

    class Meta:
        model = PluginPackage
        fields = [
            "id",
            "plugin_identifier",
            "version",
            "name",
            "description",
            "publisher",
            "icon_data_url",
            "trust",
            "signature",
            "signer",
            "review_state",
            "sha256",
            "size",
            "uploaded_at",
            "uploaded_by",
            "approved_at",
            "approved_by",
            "is_upgrade",
            "current_version",
            "contents",
            "access",
            "user_permissions",
            "public_paths",
            "outbound_hosts",
            "settings",
            "limits",
            "hooks",
            "warnings",
            "access_growth",
            "upgrade",
        ]
        read_only_fields = fields

    def get_name(self, package: PluginPackage) -> str:
        return package.parsed_manifest.name

    def get_description(self, package: PluginPackage) -> str:
        return package.parsed_manifest.description

    def get_publisher(self, package: PluginPackage) -> dict:
        publisher = package.parsed_manifest.publisher
        return {"name": publisher.name, "url": publisher.url}

    def get_icon_data_url(self, package: PluginPackage) -> str:
        encoded = base64.b64encode(bytes(package.icon_bytes)).decode("ascii")
        return f"data:{package.icon_media_type};base64,{encoded}"

    def get_signer(self, package: PluginPackage) -> dict | None:
        if package.signature_status == SignatureStatus.ABSENT:
            return None
        key_name = package.signer_key_name if package.trust == Trust.TRUSTED else None
        return {"key_name": key_name, "key_id": package.signer_key_id}

    def get_is_upgrade(self, package: PluginPackage) -> bool:
        """Whether approving the package upgrades an installed plugin."""
        return (
            package.review_state == ReviewState.PENDING
            and package.plugin.current_package_id is not None
        )

    def get_current_version(self, package: PluginPackage) -> str | None:
        current = package.plugin.current_package
        return current.version if current is not None else None

    def get_contents(self, package: PluginPackage) -> dict:
        manifest = package.parsed_manifest
        return {
            "has_spa": manifest.spa is not None,
            "has_backend": manifest.backend is not None,
            "has_database": manifest.database is not None,
            "spa_file_count": package.spa_file_count,
            "spa_bytes": package.spa_bytes,
            "wheel_count": package.wheel_count,
            "migration_count": package.migration_count,
        }

    def get_access(self, package: PluginPackage) -> list[dict]:
        return declared_access_rows(package.parsed_manifest)

    def get_user_permissions(self, package: PluginPackage) -> list[dict]:
        return [
            {
                "action": permission.action,
                "label": action_label(permission.action),
                "description": permission.description,
                "defaults": permission.defaults.model_dump(),
            }
            for permission in package.parsed_manifest.user_permissions
        ]

    def get_public_paths(self, package: PluginPackage) -> list[dict]:
        return [public_path.model_dump() for public_path in package.parsed_manifest.public_paths]

    def get_outbound_hosts(self, package: PluginPackage) -> list[dict]:
        return [outbound.model_dump() for outbound in package.parsed_manifest.outbound_hosts]

    def get_settings(self, package: PluginPackage) -> list[dict]:
        return [
            {
                "key": setting.key,
                "type": setting.type,
                "label": setting.label,
                "description": setting.description,
                "required": setting.required,
                "has_default": setting.default is not None,
            }
            for setting in package.parsed_manifest.settings
        ]

    def get_limits(self, package: PluginPackage) -> dict | None:
        limits = package.parsed_manifest.limits
        return limits.model_dump() if limits else None

    def get_hooks(self, package: PluginPackage) -> dict:
        return package.parsed_manifest.hooks.model_dump(
            include={"install", "upgrade", "org_removed"}
        )

    def get_warnings(self, package: PluginPackage) -> list[dict]:
        return review_warnings(package.parsed_manifest, package.trust)

    @extend_schema_field(AccessGrowthSerializer(allow_null=True))
    def get_access_growth(self, package: PluginPackage) -> dict | None:
        """What the new version may do that its baseline may not; null for a first install and
        for a decided package."""
        review = self._upgrade_review(package)
        return AccessGrowthSerializer(review.growth).data if review is not None else None

    @extend_schema_field(UpgradeReviewSerializer(allow_null=True))
    def get_upgrade(self, package: PluginPackage) -> dict | None:
        review = self._upgrade_review(package)
        return UpgradeReviewSerializer(review.review).data if review is not None else None

    def _upgrade_review(self, package: PluginPackage) -> PackageUpgradeReview | None:
        # Both fields read one review, computed once per package.
        if package.pk not in self._reviews:
            self._reviews[package.pk] = review_upgrade(package)
        return self._reviews[package.pk]


class PluginSummarySerializer(serializers.ModelSerializer):
    """A plugin in the SuperAdmin list; expects a `Plugin.objects.with_summary()` row."""

    trust = serializers.SerializerMethodField()
    current_version = serializers.SerializerMethodField()
    icon_url = serializers.SerializerMethodField()
    frame_origin = serializers.SerializerMethodField()
    grant_count = serializers.IntegerField()
    pending_package = serializers.SerializerMethodField()
    state = serializers.ChoiceField(choices=PluginState.choices)
    needs_attention = serializers.BooleanField(
        help_text=(
            "A data removal failed for good, the plugin node failed to remove the plugin, "
            "some of a grant's data could not be deleted yet, the open upgrade failed, or an "
            "organization's upgrade failed."
        )
    )
    upgrade = serializers.SerializerMethodField()

    class Meta:
        model = Plugin
        fields = [
            "identifier",
            "name",
            "description",
            "state",
            "trust",
            "current_version",
            "icon_url",
            "frame_origin",
            "grant_count",
            "pending_package",
            "purge_after",
            "needs_attention",
            "upgrade",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(UpgradeSummarySerializer(allow_null=True))
    def get_upgrade(self, plugin: Plugin) -> dict | None:
        """The open upgrade, if any."""
        upgrade = open_upgrade_from_summary(plugin)
        if upgrade is None:
            return None
        return {"to_version": upgrade.to_version, "stage": upgrade.stage, "failed": upgrade.failed}

    def get_trust(self, plugin: Plugin) -> str | None:
        package = plugin.current_package or self._pending(plugin)
        return package.trust if package else None

    def get_current_version(self, plugin: Plugin) -> str | None:
        return plugin.current_package.version if plugin.current_package else None

    def get_icon_url(self, plugin: Plugin) -> str | None:
        return icon_url(plugin)

    def get_frame_origin(self, plugin: Plugin) -> str:
        return PluginOrigins().frame_origin(plugin.identifier)

    def get_pending_package(self, plugin: Plugin) -> dict | None:
        pending = self._pending(plugin)
        if pending is None:
            return None
        return {"id": pending.id, "version": pending.version, "trust": pending.trust}

    @staticmethod
    def _pending(plugin: Plugin) -> PluginPackage | None:
        return plugin.pending_packages[0] if plugin.pending_packages else None


class UpgradeHookCountsSerializer(serializers.Serializer):
    upgrading = serializers.IntegerField()
    upgrade_failed = serializers.IntegerField()


class PluginDetailSerializer(PluginSummarySerializer):
    """A plugin's detail page; expects a `Plugin.objects.with_summary()` row."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._databases: dict[int, PluginDatabase | None] = {}

    current_package = serializers.SerializerMethodField()
    allowed_actions = serializers.SerializerMethodField()
    purge_progress = serializers.SerializerMethodField()
    open_upgrade = serializers.SerializerMethodField()
    last_upgrade = serializers.SerializerMethodField()
    upgrade_hooks = serializers.SerializerMethodField()

    class Meta(PluginSummarySerializer.Meta):
        fields = [
            *PluginSummarySerializer.Meta.fields,
            "current_package",
            "allowed_actions",
            "uninstall_requested_at",
            "purge_started_at",
            "purge_progress",
            "open_upgrade",
            "last_upgrade",
            "upgrade_hooks",
        ]
        read_only_fields = fields

    @extend_schema_field(PluginUpgradeSerializer(allow_null=True))
    def get_open_upgrade(self, plugin: Plugin) -> dict | None:
        upgrade = open_upgrade_from_summary(plugin)
        return self._upgrade(plugin, upgrade) if upgrade is not None else None

    @extend_schema_field(PluginUpgradeSerializer(allow_null=True))
    def get_last_upgrade(self, plugin: Plugin) -> dict | None:
        """The latest upgrade that is over."""
        upgrade = (
            PluginUpgrade.objects.filter(plugin=plugin)
            .exclude(stage__in=OPEN_UPGRADE_STAGES)
            .select_related("started_by", "from_package", "to_package")
            .defer("from_package__icon_bytes", "to_package__icon_bytes")
            .order_by("-started_at", "-pk")
            .first()
        )
        return self._upgrade(plugin, upgrade) if upgrade is not None else None

    @extend_schema_field(UpgradeHookCountsSerializer)
    def get_upgrade_hooks(self, plugin: Plugin) -> dict[str, int]:
        """How many organizations are still being upgraded, and how many failed."""
        counts = dict(
            PluginGrant.objects.filter(
                plugin=plugin, state__in=(GrantState.UPGRADING, GrantState.UPGRADE_FAILED)
            )
            .values("state")
            .annotate(count=Count("pk"))
            .values_list("state", "count")
        )
        return {
            "upgrading": counts.get(GrantState.UPGRADING, 0),
            "upgrade_failed": counts.get(GrantState.UPGRADE_FAILED, 0),
        }

    def _upgrade(self, plugin: Plugin, upgrade: PluginUpgrade) -> dict:
        if plugin.pk not in self._databases:
            self._databases[plugin.pk] = (
                PluginDatabase.objects.filter(plugin=plugin).only("pk", "ledger").first()
            )
        return PluginUpgradeSerializer(
            upgrade, context={"plugin_database": self._databases[plugin.pk]}
        ).data

    @extend_schema_field(
        serializers.ListField(
            child=serializers.ChoiceField(
                choices=[action.value for action in PluginLifecycleAction]
            )
        )
    )
    def get_allowed_actions(self, plugin: Plugin) -> list[str]:
        """The lifecycle actions the plugin allows now: the only input of the frontend's buttons."""
        facts = PluginActionFacts.of(plugin, open_upgrade_from_summary(plugin))
        return [action.value for action in allowed_plugin_actions(plugin, facts)]

    @extend_schema_field(PluginPurgeProgressSerializer(allow_null=True))
    def get_purge_progress(self, plugin: Plugin) -> dict | None:
        progress = purge_progress(plugin)
        return PluginPurgeProgressSerializer(progress).data if progress is not None else None

    def get_current_package(self, plugin: Plugin) -> dict | None:
        if plugin.current_package_id is None:
            return None
        # The summary queryset defers the manifest and icon; the review needs both.
        package = PluginPackage.objects.select_related("plugin", "uploaded_by", "approved_by").get(
            pk=plugin.current_package_id
        )
        return PackageReviewSerializer(package).data


class PluginGrantSerializer(serializers.ModelSerializer):
    """A grant in the SuperAdmin's list: a `PluginGrant.objects.with_admin_details()` row, with
    `owned_resource_count` set by `with_owned_resource_counts`."""

    plugin_identifier = serializers.CharField(source="plugin.identifier")
    organization = serializers.SerializerMethodField()
    granted_by = UserRefSerializer(source="created_by", allow_null=True)
    granted_at = serializers.DateTimeField(source="created_at")
    service_account = serializers.SerializerMethodField()
    install_hook = serializers.SerializerMethodField()
    upgrade_hook = serializers.SerializerMethodField()
    owned_resource_count = serializers.IntegerField()
    allowed_actions = serializers.SerializerMethodField()
    suspension_cause = serializers.ChoiceField(choices=SuspensionCause.choices, allow_null=True)
    org_removed_hook = serializers.SerializerMethodField()

    class Meta:
        model = PluginGrant
        fields = [
            "id",
            "plugin_identifier",
            "organization",
            "state",
            "granted_by",
            "granted_at",
            "suspended_at",
            "suspension_cause",
            "purge_after",
            "purge_started_at",
            "last_purge_error",
            "last_hook_error",
            "service_account",
            "install_hook",
            "installed_version",
            "upgrade_hook",
            "org_removed_hook",
            "owned_resource_count",
            "allowed_actions",
        ]
        read_only_fields = fields

    @extend_schema_field(UpgradeHookSerializer(allow_null=True))
    def get_upgrade_hook(self, grant: PluginGrant) -> dict | None:
        """The grant's latest upgrade job."""
        if not grant.upgrade_jobs:
            return None
        job = grant.upgrade_jobs[0]
        return {
            "state": job.state,
            "attempt": job.attempt,
            "from_version": job.previous_version,
            "next_attempt_at": datetime_text(job.next_attempt_at),
            "started_at": datetime_text(job.claimed_at),
            "finished_at": datetime_text(job.finished_at),
            "error": job.error,
        }

    def get_organization(self, grant: PluginGrant) -> dict:
        return {"id": grant.org_id, "name": grant.org.name}

    def get_service_account(self, grant: PluginGrant) -> dict | None:
        # A grant of a plugin without a backend has none (reverse one-to-one).
        account = getattr(grant, "service_account", None)
        if account is None:
            return None
        return {
            "created_at": datetime_text(account.created_at),
            "key_last_used_at": datetime_text(grant.key_last_used_at),
        }

    def get_install_hook(self, grant: PluginGrant) -> dict | None:
        if not grant.install_jobs:
            return None
        job = grant.install_jobs[0]
        return {
            "state": job.state,
            "attempt": job.attempt,
            "started_at": datetime_text(job.claimed_at),
            "finished_at": datetime_text(job.finished_at),
            "error": job.error,
        }

    @extend_schema_field(OrgRemovedJobSerializer(allow_null=True))
    def get_org_removed_hook(self, grant: PluginGrant) -> dict | None:
        """The grant's latest organization removed job, while its data is deleted."""
        if not grant.org_removed_jobs:
            return None
        return OrgRemovedJobSerializer(grant.org_removed_jobs[0]).data

    @extend_schema_field(
        serializers.ListField(
            child=serializers.ChoiceField(choices=[action.value for action in GrantAction])
        )
    )
    def get_allowed_actions(self, grant: PluginGrant) -> list[str]:
        """The lifecycle actions the grant allows now: the only input of the frontend's buttons."""
        return [action.value for action in allowed_grant_actions(grant)]
