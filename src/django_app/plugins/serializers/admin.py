import base64

from rest_framework import serializers

from plugins.models import Plugin, PluginGrant, PluginPackage, SignatureStatus, Trust
from plugins.origins import PluginOrigins
from plugins.packages.review import action_label, resource_label, review_warnings


def icon_url(plugin: Plugin) -> str | None:
    """Public URL of a plugin's approved icon; the version busts browser caches on upgrade."""
    if plugin.current_package is None:
        return None
    return f"/api/plugin-public/{plugin.identifier}/icon/?v={plugin.current_package.version}"


class UserRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()


class PackageUploadSerializer(serializers.Serializer):
    file = serializers.FileField(allow_empty_file=False)


class PackageApprovalSerializer(serializers.Serializer):
    untrusted_acknowledged = serializers.BooleanField(required=False, default=False)


class GrantCreateSerializer(serializers.Serializer):
    organization_id = serializers.IntegerField(min_value=1)


class PackageReviewSerializer(serializers.ModelSerializer):
    """Everything a SuperAdmin reviews before approving a package."""

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
        return False

    def get_current_version(self, package: PluginPackage) -> None:
        return None

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
        return [
            {
                "resource_type": declaration.resource_type,
                "resource_label": resource_label(declaration.resource_type),
                "actions": list(declaration.actions),
                "reason": declaration.reason,
            }
            for declaration in package.parsed_manifest.access
        ]

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

    def get_access_growth(self, package: PluginPackage) -> None:
        return None


class PluginSummarySerializer(serializers.ModelSerializer):
    """A plugin in the SuperAdmin list; expects a `Plugin.objects.with_summary()` row."""

    trust = serializers.SerializerMethodField()
    current_version = serializers.SerializerMethodField()
    icon_url = serializers.SerializerMethodField()
    frame_origin = serializers.SerializerMethodField()
    grant_count = serializers.IntegerField()
    pending_package = serializers.SerializerMethodField()

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
            "created_at",
        ]
        read_only_fields = fields

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


class PluginDetailSerializer(PluginSummarySerializer):
    current_package = serializers.SerializerMethodField()

    class Meta(PluginSummarySerializer.Meta):
        fields = [*PluginSummarySerializer.Meta.fields, "current_package"]
        read_only_fields = fields

    def get_current_package(self, plugin: Plugin) -> dict | None:
        if plugin.current_package_id is None:
            return None
        # The summary queryset defers the manifest and icon; the review needs both.
        package = PluginPackage.objects.select_related("plugin", "uploaded_by", "approved_by").get(
            pk=plugin.current_package_id
        )
        return PackageReviewSerializer(package).data


class PluginGrantSerializer(serializers.ModelSerializer):
    plugin_identifier = serializers.CharField(source="plugin.identifier")
    organization = serializers.SerializerMethodField()
    granted_by = UserRefSerializer(source="created_by", allow_null=True)
    granted_at = serializers.DateTimeField(source="created_at")

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
            "purge_after",
            "last_hook_error",
        ]
        read_only_fields = fields

    def get_organization(self, grant: PluginGrant) -> dict:
        return {"id": grant.org_id, "name": grant.org.name}
