from rest_framework import serializers

from tables.models import Agent
from tables.models.knowledge_models.naive_rag_models import NaiveRagSearchConfig


class NaiveRagSearchConfigImportSerializer(serializers.ModelSerializer):
    agent = serializers.PrimaryKeyRelatedField(
        queryset=Agent.objects.all(), write_only=True
    )

    class Meta:
        model = NaiveRagSearchConfig
        fields = "__all__"
