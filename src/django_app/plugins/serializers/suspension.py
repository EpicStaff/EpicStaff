from rest_framework import serializers


class NamedRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class PreviewNamedListSerializer(serializers.Serializer):
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
    organization = PreviewNamedListSerializer(source="organization_flows")
    plugin = PreviewNamedListSerializer(source="plugin_flows")


class OwnedResourceCountSerializer(serializers.Serializer):
    model = serializers.CharField()
    label = serializers.CharField()
    count = serializers.IntegerField()


class PreviewGrantSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    state = serializers.CharField()


class PreviewPluginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    name = serializers.CharField()


class PreviewOrganizationSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    name = serializers.CharField()


class PreviewDefaultModelSerializer(serializers.Serializer):
    setting = serializers.CharField()
    config = NamedRowSerializer()


class SuspendPreviewSerializer(serializers.Serializer):
    """What suspending a grant stops; renders a `SuspendPreview`."""

    grant = PreviewGrantSerializer()
    plugin = PreviewPluginSerializer(source="grant.plugin")
    organization = PreviewOrganizationSerializer(source="grant.org")
    data_kept_until = serializers.DateTimeField()
    owned_resources = OwnedResourceCountSerializer(many=True)
    flows = PreviewFlowsSerializer(source="*")
    running_sessions = PreviewSessionListSerializer()
    triggers = PreviewTriggerListSerializer()
    realtime_agents = PreviewNamedListSerializer()
    voice_channels = PreviewNamedListSerializer()
    default_models = PreviewDefaultModelSerializer(many=True)
