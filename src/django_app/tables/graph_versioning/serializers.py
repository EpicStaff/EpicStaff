from rbac.authorship import UserSummarySerializer
from rest_framework import serializers

from tables.models import Graph, GraphVersion


class GraphVersionCreateSerializer(serializers.Serializer):
    graph_id = serializers.PrimaryKeyRelatedField(queryset=Graph.objects.all(), source="graph")
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, default="", allow_blank=True)


class GraphVersionReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = GraphVersion
        fields = [
            "id",
            "graph_id",
            "name",
            "description",
            "created_at",
        ]


class GraphVersionUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = GraphVersion
        fields = ["name", "description"]
        extra_kwargs = {
            "name": {"required": False},
            "description": {"required": False, "allow_blank": True},
        }

    def update(self, instance, validated_data):
        """Write only the renamed fields.

        A full save would write back the snapshot loaded with `instance`, undoing a scrub
        of that snapshot (`VersionSnapshotAuthorshipScrubber`) that ran since.
        """
        for field_name, value in validated_data.items():
            setattr(instance, field_name, value)
        instance.save(update_fields=list(validated_data))
        return instance

    def to_representation(self, instance):
        return GraphVersionReadSerializer(instance, context=self.context).data


class RestoreVersionInputSerializer(serializers.Serializer):
    save_version = serializers.IntegerField(required=True)


class GraphVersionNodeAuthorshipSerializer(serializers.Serializer):
    """A node's author and last editor as recorded when a version was saved."""

    created_by = UserSummarySerializer(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True, allow_null=True)
    last_edited_by = UserSummarySerializer(read_only=True, allow_null=True)
    last_edited_at = serializers.DateTimeField(read_only=True, allow_null=True)


class GraphVersionPreviewResponseSerializer(serializers.Serializer):
    """What restoring a version would apply; renders `GraphVersioningService.preview_version`.

    `node_authorship` is keyed by the snapshot's node ids and empty for a version saved
    before node authorship was recorded.
    """

    snapshot = serializers.DictField(read_only=True)
    warnings = serializers.ListField(child=serializers.DictField(), read_only=True)
    node_authorship = serializers.DictField(
        child=GraphVersionNodeAuthorshipSerializer(), read_only=True
    )
