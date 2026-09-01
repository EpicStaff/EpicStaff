from rest_framework import serializers

from tables.models import McpTool


class McpToolImportSerializer(serializers.ModelSerializer):
    # `auth` holds a bearer/OAuth secret. write_only keeps it out of
    # `serializer(instance).data`, so it is never included in an export
    # payload (EST-3783). It still accepts a value on import/create so
    # existing create flows are unaffected; re-imported tools simply come
    # back with auth unset and must have it re-entered manually — the
    # secure default, mirroring how LLMConfig/EmbeddingConfig etc. keep
    # `api_key` out of exports (see BaseConfigImportSerializer).
    auth = serializers.CharField(
        write_only=True, required=False, allow_null=True, allow_blank=True
    )

    class Meta:
        model = McpTool
        exclude = ["labels", "created_by", "auth_secret"]
