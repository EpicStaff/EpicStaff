"""Upgrades, their review, backups and restores, as the SuperAdmin's plugin pages show them."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from plugins.databases.backup_records import ListedBackup
from plugins.lifecycle.open_upgrades import database_changed
from plugins.models import PluginDatabase, PluginDatabaseRestore, PluginUpgrade
from plugins.packages.upgrade_review import AccessGrowth
from plugins.serializers.common import UserRefSerializer


class UpgradeApprovalSerializer(serializers.Serializer):
    """The approval body: the untrusted acknowledgement, and for an upgrade the baseline the
    review was computed against, the new-access acknowledgement and the settings it needs."""

    untrusted_acknowledged = serializers.BooleanField(required=False, default=False)
    access_growth_acknowledged = serializers.BooleanField(required=False, default=False)
    reviewed_against_package_id = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=1
    )
    settings = serializers.DictField(
        child=serializers.JSONField(allow_null=True), required=False, allow_null=True, default=None
    )


class RestoreBackupRefSerializer(serializers.Serializer):
    id = serializers.IntegerField(allow_null=True)
    file_name = serializers.CharField()
    reason = serializers.CharField(allow_null=True)


class PluginRestoreSerializer(serializers.ModelSerializer):
    """A restore of a backup into a plugin's database, and how it went."""

    backup = serializers.SerializerMethodField()
    requested_by = UserRefSerializer(allow_null=True)

    class Meta:
        model = PluginDatabaseRestore
        fields = [
            "id",
            "backup",
            "state",
            "step",
            "pre_restore_backup_id",
            "last_error",
            "requested_by",
            "requested_at",
            "finished_at",
        ]
        read_only_fields = fields

    @extend_schema_field(RestoreBackupRefSerializer)
    def get_backup(self, restore: PluginDatabaseRestore) -> dict:
        backup = restore.backup
        return {
            "id": restore.backup_id,
            "file_name": restore.backup_file_name,
            "reason": backup.reason if backup is not None else None,
        }


class PluginUpgradeSerializer(serializers.ModelSerializer):
    """An upgrade of a plugin. Expects the plugin's database record (or None) as
    `plugin_database` in the context, for `database_changed`."""

    failed = serializers.BooleanField()
    database_changed = serializers.SerializerMethodField()
    restore = serializers.SerializerMethodField()
    started_by = UserRefSerializer(allow_null=True)

    class Meta:
        model = PluginUpgrade
        fields = [
            "id",
            "from_version",
            "to_version",
            "stage",
            "step",
            "failed",
            "failed_at",
            "last_error",
            "adds_backend",
            "database_changed",
            "backup_id",
            "restore",
            "started_by",
            "started_at",
            "maintenance_started_at",
            "migrations_started_at",
            "finished_at",
        ]
        read_only_fields = fields

    def get_database_changed(self, upgrade: PluginUpgrade) -> bool:
        database: PluginDatabase | None = self.context.get("plugin_database")
        return database_changed(upgrade, database)

    @extend_schema_field(PluginRestoreSerializer(allow_null=True))
    def get_restore(self, upgrade: PluginUpgrade) -> dict | None:
        """The upgrade's latest restore."""
        restore = (
            upgrade.restores.select_related("backup", "requested_by")
            .order_by("-requested_at", "-pk")
            .first()
        )
        return PluginRestoreSerializer(restore).data if restore is not None else None


class UpgradeSummarySerializer(serializers.Serializer):
    to_version = serializers.CharField()
    stage = serializers.CharField()
    failed = serializers.BooleanField()


class PluginBackupUpgradeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    to_version = serializers.CharField(
        help_text=(
            "The version the upgrade was going to when the backup was taken; a newer version "
            "that later replaced a failed target does not change it."
        )
    )


class PluginBackupSerializer(serializers.Serializer):
    """One backup, with its upgrade loaded."""

    id = serializers.IntegerField(source="backup.pk")
    file_name = serializers.CharField(source="backup.file_name")
    reason = serializers.CharField(source="backup.reason")
    version = serializers.CharField(source="backup.version")
    upgrade = serializers.SerializerMethodField()
    size_bytes = serializers.IntegerField(source="backup.size_bytes")
    created_at = serializers.DateTimeField(source="backup.created_at")
    restorable = serializers.BooleanField()
    not_restorable_reason = serializers.ChoiceField(
        choices=["earlier_upgrade", "not_now", "mismatch"], allow_null=True
    )

    @extend_schema_field(PluginBackupUpgradeSerializer(allow_null=True))
    def get_upgrade(self, listed: ListedBackup) -> dict | None:
        backup = listed.backup
        upgrade = backup.upgrade
        if upgrade is None:
            return None
        # Null when the upgrade was not open as the backup was recorded: its target since.
        return {"id": upgrade.pk, "to_version": backup.taken_for_version or upgrade.to_version}


class PluginBackupListSerializer(serializers.Serializer):
    verification_phrase = serializers.CharField()
    backups = serializers.SerializerMethodField()

    @extend_schema_field(PluginBackupSerializer(many=True))
    def get_backups(self, backup_list) -> list[dict]:
        return PluginBackupSerializer(backup_list.backups, many=True).data


class AccessGrowthAccessSerializer(serializers.Serializer):
    resource_type = serializers.CharField()
    resource_label = serializers.CharField()
    actions = serializers.ListField(child=serializers.CharField())
    reason = serializers.CharField()


class AccessGrowthHostSerializer(serializers.Serializer):
    host = serializers.CharField()
    reason = serializers.CharField()


class AccessGrowthPublicPathSerializer(serializers.Serializer):
    path = serializers.CharField()
    match = serializers.ChoiceField(choices=["exact", "prefix"])
    methods = serializers.ListField(child=serializers.CharField())
    rate_limit_per_minute = serializers.IntegerField()
    max_body_kb = serializers.IntegerField()
    change = serializers.ChoiceField(choices=["new", "widened"])


class AccessGrowthSerializer(serializers.Serializer):
    requires_acknowledgement = serializers.BooleanField()
    access = AccessGrowthAccessSerializer(many=True)
    outbound_hosts = AccessGrowthHostSerializer(many=True)
    public_paths = AccessGrowthPublicPathSerializer(many=True)

    def to_representation(self, growth: AccessGrowth) -> dict:
        return {
            "requires_acknowledgement": growth.requires_acknowledgement,
            "access": growth.access,
            "outbound_hosts": growth.outbound_hosts,
            "public_paths": growth.public_paths,
        }


class SettingNeededSerializer(serializers.Serializer):
    key = serializers.CharField(source="setting.key")
    type = serializers.CharField(source="setting.type")
    label = serializers.CharField(source="setting.label")
    description = serializers.CharField(source="setting.description")
    reason = serializers.ChoiceField(choices=["required", "invalid"])
    values = serializers.ListField(
        source="setting.values", child=serializers.CharField(), allow_null=True
    )


class UserPermissionChangesSerializer(serializers.Serializer):
    added = serializers.ListField(child=serializers.CharField())
    removed = serializers.ListField(child=serializers.CharField())
    defaults_changed = serializers.ListField(child=serializers.CharField())


class UpgradeSettingsSerializer(serializers.Serializer):
    added = serializers.ListField(child=serializers.CharField(), source="settings_added")
    removed = serializers.ListField(child=serializers.CharField(), source="settings_removed")
    needed = SettingNeededSerializer(many=True, source="settings_needed")


class UpgradeBackupSerializer(serializers.Serializer):
    required = serializers.BooleanField(source="backup_required")
    database_size_bytes = serializers.IntegerField(allow_null=True)
    database_name = serializers.CharField(allow_null=True)


class UpgradeReviewSerializer(serializers.Serializer):
    """What approving a new version will change, apart from the access it needs approved."""

    baseline_package_id = serializers.IntegerField()
    from_version = serializers.CharField()
    replaces_version = serializers.CharField(allow_null=True)
    trust_change = serializers.ChoiceField(
        choices=["none", "became_untrusted", "became_trusted", "signer_changed"]
    )
    maintenance = serializers.BooleanField()
    backend = serializers.ChoiceField(choices=["unchanged", "added"])
    database = serializers.ChoiceField(choices=["unchanged", "added", "none"])
    migrations_added = serializers.ListField(child=serializers.CharField())
    hooks_added = serializers.ListField(child=serializers.CharField())
    hooks_removed = serializers.ListField(child=serializers.CharField())
    has_upgrade_hook = serializers.BooleanField()
    user_permissions = UserPermissionChangesSerializer()
    settings = UpgradeSettingsSerializer(source="*")
    limits_changed = serializers.ListField(child=serializers.CharField())
    navigation_changed = serializers.BooleanField(
        help_text="The app menu's items differ from the baseline's: label, path, icon file or order."
    )
    backup = UpgradeBackupSerializer(source="*")
    organizations_going_offline = serializers.IntegerField()
    cancellable = serializers.BooleanField()
