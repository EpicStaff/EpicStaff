from rest_framework import serializers

from plugins.lifecycle.suspend_preview_service import SuspendPreview


class NamedRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class PreviewFlowListSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    items = NamedRowSerializer(many=True)


class PreviewSessionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    flow = NamedRowSerializer()
    status = serializers.CharField()
    created_at = serializers.DateTimeField()


class PreviewSessionListSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    items = PreviewSessionSerializer(many=True)


class PreviewTriggerSerializer(serializers.Serializer):
    kind = serializers.CharField()
    node_id = serializers.IntegerField()
    node_name = serializers.CharField()
    flow = NamedRowSerializer()


class PreviewTriggerListSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    items = PreviewTriggerSerializer(many=True)


class PreviewFlowsSerializer(serializers.Serializer):
    organization = PreviewFlowListSerializer(source="organization_flows")
    plugin = PreviewFlowListSerializer(source="plugin_flows")


class OwnedResourceCountSerializer(serializers.Serializer):
    model = serializers.CharField()
    label = serializers.CharField()
    count = serializers.IntegerField()


class PreviewDefaultModelSerializer(serializers.Serializer):
    setting = serializers.CharField()
    config = NamedRowSerializer()


class SuspendPreviewSerializer(serializers.Serializer):
    """What suspending a grant stops; renders a `SuspendPreview`."""

    grant = serializers.SerializerMethodField()
    plugin = serializers.SerializerMethodField()
    organization = serializers.SerializerMethodField()
    data_kept_until = serializers.DateTimeField()
    owned_resources = OwnedResourceCountSerializer(many=True)
    flows = PreviewFlowsSerializer(source="*")
    running_sessions = PreviewSessionListSerializer()
    triggers = PreviewTriggerListSerializer()
    realtime_agents = PreviewFlowListSerializer()
    voice_channels = PreviewFlowListSerializer()
    default_models = PreviewDefaultModelSerializer(many=True)

    def get_grant(self, preview: SuspendPreview) -> dict:
        return {"id": preview.grant.pk, "state": preview.grant.state}

    def get_plugin(self, preview: SuspendPreview) -> dict:
        plugin = preview.grant.plugin
        return {"identifier": plugin.identifier, "name": plugin.name}

    def get_organization(self, preview: SuspendPreview) -> dict:
        return {"id": preview.grant.org_id, "name": preview.grant.org.name}
