from rest_framework import serializers

from plugins.configuration.setting_values import SECRET_TYPE, SettingState
from plugins.nodes.plugin_runtime_service import PluginRuntime
from plugins.serializers.common import UserRefSerializer


class PluginSettingStateSerializer(serializers.Serializer):
    """One setting as the Settings tab shows it. A secret's value never leaves the server."""

    key = serializers.CharField(source="setting.key")
    type = serializers.CharField(source="setting.type")
    label = serializers.CharField(source="setting.label")
    description = serializers.CharField(source="setting.description")
    required = serializers.BooleanField(source="setting.required")
    values = serializers.ListField(source="setting.values", allow_null=True)
    default = serializers.SerializerMethodField()
    value = serializers.SerializerMethodField()
    is_set = serializers.SerializerMethodField()
    tail = serializers.SerializerMethodField()
    updated_at = serializers.DateTimeField(source="stored.updated_at", allow_null=True)
    updated_by = serializers.SerializerMethodField()

    def get_default(self, state: SettingState):
        return None if state.setting.type == SECRET_TYPE else state.setting.default

    def get_value(self, state: SettingState):
        if state.stored is None or state.setting.type == SECRET_TYPE:
            return None
        return state.stored.value

    def get_is_set(self, state: SettingState) -> bool:
        return state.stored is not None

    def get_tail(self, state: SettingState) -> str | None:
        if state.stored is None or state.setting.type != SECRET_TYPE:
            return None
        return state.stored.tail or None

    def get_updated_by(self, state: SettingState) -> dict | None:
        if state.stored is None or state.stored.updated_by is None:
            return None
        return UserRefSerializer(state.stored.updated_by).data


class PluginSettingsResponseSerializer(serializers.Serializer):
    settings = PluginSettingStateSerializer(source="states", many=True)
    missing_required = serializers.ListField(child=serializers.CharField())


class PluginSettingsUpdateSerializer(serializers.Serializer):
    values = serializers.DictField(child=serializers.JSONField(allow_null=True))


class PluginLimitsResponseSerializer(serializers.Serializer):
    requested = serializers.DictField()
    platform_max = serializers.DictField()
    overrides = serializers.DictField()
    effective = serializers.DictField()
    enforced = serializers.DictField()
    has_database = serializers.BooleanField()


class PluginLimitsUpdateSerializer(serializers.Serializer):
    overrides = serializers.DictField(child=serializers.JSONField(allow_null=True))


class RuntimeDatabaseServerSerializer(serializers.Serializer):
    name = serializers.CharField()
    host = serializers.CharField()
    port = serializers.IntegerField()


class RuntimeDatabaseRolesSerializer(serializers.Serializer):
    owner = serializers.CharField(source="owner_role")
    app = serializers.CharField(source="app_role")
    job = serializers.CharField(source="job_role")


class RuntimeDatabaseMigrationsSerializer(serializers.Serializer):
    applied = serializers.ListField(
        child=serializers.CharField(), source="record.applied_migrations"
    )
    in_package = serializers.IntegerField(source="migrations_in_package")


class PluginRuntimeDatabaseSerializer(serializers.Serializer):
    """A plugin's database as the Runtime tab shows it: names, ledger and limits, never its
    password."""

    state = serializers.CharField(source="record.state")
    server = RuntimeDatabaseServerSerializer(source="record.server")
    database_name = serializers.CharField(source="record.database_name")
    roles = RuntimeDatabaseRolesSerializer(source="record")
    migrations = RuntimeDatabaseMigrationsSerializer(source="*")
    connection_limit = serializers.IntegerField()
    statement_timeout_seconds = serializers.IntegerField()
    size_bytes = serializers.IntegerField(source="record.size_bytes", allow_null=True)
    last_error = serializers.CharField(source="record.last_error", allow_null=True)
    ready_at = serializers.DateTimeField(source="record.ready_at", allow_null=True)
    limits_restored_at = serializers.DateTimeField(
        source="record.limits_restored_at", allow_null=True
    )


class RuntimeOutboundHostSerializer(serializers.Serializer):
    host = serializers.CharField()
    reason = serializers.CharField()


class PluginRuntimeEgressSerializer(serializers.Serializer):
    """The hosts the backend may reach; an empty list means no outbound access. The Runtime
    tab exists only for a backend, and every backend has this section."""

    hosts = RuntimeOutboundHostSerializer(source="outbound_hosts", many=True)


class RuntimeUpgradeSerializer(serializers.Serializer):
    from_version = serializers.CharField()
    to_version = serializers.CharField()


class PluginRuntimeResponseSerializer(serializers.Serializer):
    """Where a plugin's backend runs, what its node last reported, its database and its
    outbound hosts. No password of any kind is ever part of it. `upgrade` is set exactly while
    the node runs a package other than the current one, whose database, limits and hosts it
    shows."""

    node = serializers.SerializerMethodField()
    placement = serializers.SerializerMethodField()
    database = PluginRuntimeDatabaseSerializer(allow_null=True)
    egress = PluginRuntimeEgressSerializer(source="*")
    upgrade = RuntimeUpgradeSerializer(allow_null=True)

    def get_node(self, runtime: PluginRuntime) -> dict | None:
        node = runtime.node
        if node is None:
            return None
        return {
            "name": node.name,
            "online": runtime.node_online,
            "last_seen_at": _datetime(node.last_seen_at),
            "agent_version": node.agent_version,
        }

    def get_placement(self, runtime: PluginRuntime) -> dict | None:
        placement = runtime.placement
        if placement is None:
            return None
        return {
            "port": placement.port,
            "unix_uid": placement.unix_uid,
            "desired_state": runtime.desired_state,
            "blocked_reason": runtime.blocked_reason,
            "observed_state": placement.observed_state,
            "observed_version": placement.observed_version,
            "health": placement.health,
            "pid": placement.pid,
            "restarts": placement.restarts,
            "rss_mb": placement.rss_mb,
            "last_error": placement.last_error,
            "log_tail": list(placement.log_tail or []),
            "last_report_at": _datetime(placement.last_report_at),
        }


def _datetime(value) -> str | None:
    return serializers.DateTimeField().to_representation(value) if value is not None else None
