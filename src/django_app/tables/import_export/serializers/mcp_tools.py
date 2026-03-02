from rest_framework import serializers

from tables.models import McpTool


class McpToolImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = McpTool
        fields = "__all__"
