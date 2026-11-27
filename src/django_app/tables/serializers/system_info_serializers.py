from rest_framework import serializers


class SystemInfoFeaturesSerializer(serializers.Serializer):
    chats = serializers.BooleanField()
    plugins = serializers.BooleanField()
    session_audit = serializers.BooleanField()
    user_audit = serializers.BooleanField()


class SystemInfoSerializer(serializers.Serializer):
    """Build identity and feature switches of this installation.

    The build fields are null when the image was built without CI build arguments.
    """

    version = serializers.CharField(allow_null=True)
    git_ref = serializers.CharField(allow_null=True)
    git_sha = serializers.CharField(allow_null=True)
    commit_date = serializers.CharField(allow_null=True)
    import_version = serializers.IntegerField()
    features = SystemInfoFeaturesSerializer()
