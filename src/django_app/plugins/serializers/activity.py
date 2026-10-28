from rbac.models import Organization
from rest_framework import serializers

from plugins.models import ActivityAction, Plugin, PluginActivityEvent, PluginServiceAccount
from plugins.serializers.admin import datetime_text, declared_access_rows, icon_url


class OrganizationActivityQuerySerializer(serializers.Serializer):
    plugin = serializers.CharField(required=False, max_length=32)
    action = serializers.ChoiceField(choices=ActivityAction.choices, required=False)


class AdminActivityQuerySerializer(serializers.Serializer):
    organization_id = serializers.IntegerField(required=False, min_value=1)
    action = serializers.ChoiceField(choices=ActivityAction.choices, required=False)


class PluginActivityEventSerializer(serializers.ModelSerializer):
    """One activity event. Needs `plugin_names` and `organization_names` in its context
    (`activity_context`), so a page of events costs two queries for the names."""

    plugin = serializers.SerializerMethodField()
    organization = serializers.SerializerMethodField()
    actor = serializers.SerializerMethodField()
    on_behalf_of = serializers.SerializerMethodField()
    request = serializers.SerializerMethodField()
    target = serializers.SerializerMethodField()

    class Meta:
        model = PluginActivityEvent
        fields = [
            "id",
            "created_at",
            "plugin",
            "organization",
            "actor",
            "on_behalf_of",
            "action",
            "request",
            "target",
            "detail",
        ]
        read_only_fields = fields

    def get_plugin(self, event: PluginActivityEvent) -> dict:
        return {
            "identifier": event.plugin_identifier,
            "name": self.context["plugin_names"].get(event.plugin_identifier),
        }

    def get_organization(self, event: PluginActivityEvent) -> dict | None:
        if event.organization_id is None:
            return None
        return {
            "id": event.organization_id,
            "name": self.context["organization_names"].get(event.organization_id),
        }

    def get_actor(self, event: PluginActivityEvent) -> dict:
        return {"kind": event.actor_kind, "label": event.actor_label}

    def get_on_behalf_of(self, event: PluginActivityEvent) -> dict | None:
        if event.on_behalf_of_label is None:
            return None
        return {"user_id": event.on_behalf_of_user_id, "label": event.on_behalf_of_label}

    def get_request(self, event: PluginActivityEvent) -> dict | None:
        if event.request_method is None:
            return None
        return {
            "method": event.request_method,
            "path": event.request_path,
            "route": event.request_route,
            "status": event.response_status,
        }

    def get_target(self, event: PluginActivityEvent) -> dict | None:
        if event.target_resource_type is None and event.target_id is None:
            return None
        return {
            "resource_type": event.target_resource_type,
            "id": event.target_id,
            "label": event.target_label,
        }


def activity_context(events: list[PluginActivityEvent]) -> dict:
    """The names a page of events shows: its plugins' and organizations', two queries."""
    identifiers = {event.plugin_identifier for event in events}
    organization_ids = {event.organization_id for event in events} - {None}
    return {
        "plugin_names": dict(
            Plugin.objects.filter(identifier__in=identifiers).values_list("identifier", "name")
        )
        if identifiers
        else {},
        "organization_names": dict(
            Organization.objects.filter(pk__in=organization_ids).values_list("pk", "name")
        )
        if organization_ids
        else {},
    }


class OrganizationServiceAccountSerializer(serializers.ModelSerializer):
    """A plugin acting in the organization, with what it declared it may do there, the hosts it
    may call and whether it keeps its data in a database of its own.

    Expects an account with its grant's plugin and current package, and `key_last_used_at`.
    """

    plugin = serializers.SerializerMethodField()
    grant_state = serializers.CharField(source="grant.state")
    key_last_used_at = serializers.SerializerMethodField()
    access = serializers.SerializerMethodField()
    outbound_hosts = serializers.SerializerMethodField()
    has_database = serializers.SerializerMethodField()

    class Meta:
        model = PluginServiceAccount
        fields = [
            "plugin",
            "grant_state",
            "created_at",
            "key_last_used_at",
            "access",
            "outbound_hosts",
            "has_database",
        ]
        read_only_fields = fields

    def get_plugin(self, account: PluginServiceAccount) -> dict:
        plugin = account.grant.plugin
        return {"identifier": plugin.identifier, "name": plugin.name, "icon_url": icon_url(plugin)}

    def get_key_last_used_at(self, account: PluginServiceAccount) -> str | None:
        return datetime_text(account.key_last_used_at)

    def get_access(self, account: PluginServiceAccount) -> list[dict]:
        return declared_access_rows(account.grant.plugin.current_package.parsed_manifest)

    def get_outbound_hosts(self, account: PluginServiceAccount) -> list[dict]:
        manifest = account.grant.plugin.current_package.parsed_manifest
        return [
            {"host": outbound.host, "reason": outbound.reason}
            for outbound in manifest.outbound_hosts
        ]

    def get_has_database(self, account: PluginServiceAccount) -> bool:
        return account.grant.plugin.current_package.parsed_manifest.database is not None
