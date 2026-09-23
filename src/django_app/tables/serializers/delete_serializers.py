from rest_framework import serializers


class UserDeleteReportSerializer(serializers.Serializer):
    """What deleting a user removed, or would remove."""

    user_id = serializers.IntegerField()
    affected_resources = serializers.DictField(child=serializers.IntegerField())


class OrganizationDeleteReportSerializer(serializers.Serializer):
    """What deleting an organization removed, or would remove."""

    organization_id = serializers.IntegerField()
    affected_resources = serializers.DictField(child=serializers.IntegerField())
