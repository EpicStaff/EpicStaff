from rest_framework import serializers


class DeleteTargetSerializer(serializers.Serializer):
    """Identity of the row being deleted."""

    type = serializers.CharField()
    id = serializers.IntegerField()
    name = serializers.CharField(required=False)
    email = serializers.EmailField(required=False)


class ModelCountSerializer(serializers.Serializer):
    """Row count for one model in the cascade."""

    model = serializers.CharField()
    count = serializers.IntegerField()


class DatabaseImpactSerializer(serializers.Serializer):
    """Total and per-model row counts the delete removes."""

    total = serializers.IntegerField()
    by_model = ModelCountSerializer(many=True)


class FieldUpdateSerializer(serializers.Serializer):
    """A foreign key the delete nulls out rather than removing."""

    model = serializers.CharField()
    field = serializers.CharField()
    action = serializers.CharField()
    count = serializers.IntegerField()


class ExternalArtifactSerializer(serializers.Serializer):
    """A file outside the database that the delete orphans."""

    kind = serializers.CharField()
    prefix = serializers.CharField(required=False)
    path = serializers.CharField(required=False)
    objects = serializers.IntegerField(required=False, allow_null=True)
    bytes = serializers.IntegerField(required=False, allow_null=True)


class DeleteReportSerializer(serializers.Serializer):
    """What a delete removed, or would remove under `dry_run`."""

    dry_run = serializers.BooleanField()
    target = DeleteTargetSerializer()
    database = DatabaseImpactSerializer()
    field_updates = FieldUpdateSerializer(many=True)
    external = ExternalArtifactSerializer(many=True)
