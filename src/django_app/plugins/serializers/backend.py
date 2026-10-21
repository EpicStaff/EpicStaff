from rest_framework import serializers

from plugins.configuration.setting_values import SECRET_TYPE, SettingState
from plugins.nodes.plugin_runtime_service import PluginRuntime
from plugins.serializers.admin import UserRefSerializer


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


class PluginRuntimeResponseSerializer(serializers.Serializer):
    """Where a plugin's backend runs, what its node last reported, its database and its
    outbound hosts. No password of any kind is ever part of it."""

    node = serializers.SerializerMethodField()
    placement = serializers.SerializerMethodField()
    database = serializers.SerializerMethodField()
    egress = serializers.SerializerMethodField()

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

    def get_database(self, runtime: PluginRuntime) -> dict | None:
        database = runtime.database
        if database is None:
            return None
        record = database.record
        server = record.server
        return {
            "state": record.state,
            "server": {"name": server.name, "host": server.host, "port": server.port},
            "database_name": record.database_name,
            "roles": {"owner": record.owner_role, "app": record.app_role, "job": record.job_role},
            "migrations": {
                "applied": list(record.applied_migrations),
                "in_package": database.migrations_in_package,
            },
            "connection_limit": database.connection_limit,
            "statement_timeout_seconds": database.statement_timeout_seconds,
            "size_bytes": record.size_bytes,
            "last_error": record.last_error,
            "ready_at": _datetime(record.ready_at),
            "limits_restored_at": _datetime(record.limits_restored_at),
        }

    def get_egress(self, runtime: PluginRuntime) -> dict:
        # The Runtime tab exists only for a backend, and every backend has an egress section:
        # an empty list of hosts means no outbound access.
        return {
            "hosts": [
                {"host": outbound.host, "reason": outbound.reason}
                for outbound in runtime.outbound_hosts
            ]
        }


def _datetime(value) -> str | None:
    return serializers.DateTimeField().to_representation(value) if value is not None else None
