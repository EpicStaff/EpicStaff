from rest_framework import serializers

from tables.models import (
    CrewTag,
    AgentTag,
    GraphTag,
    LLMModelTag,
    EmbeddingModelTag,
    LLMConfigTag,
)


class BaseTagImportSerializer(serializers.ModelSerializer):
    class Meta:
        abstract = True
        model = None
        fields = "__all__"


class CrewTagImportSerializer(BaseTagImportSerializer):
    class Meta(BaseTagImportSerializer.Meta):
        model = CrewTag


class AgentTagImportSerializer(BaseTagImportSerializer):
    class Meta(BaseTagImportSerializer.Meta):
        model = AgentTag


class GraphTagImportSerializer(BaseTagImportSerializer):
    class Meta(BaseTagImportSerializer.Meta):
        model = GraphTag


class LLMModelTagImportSerializer(BaseTagImportSerializer):
    class Meta(BaseTagImportSerializer.Meta):
        model = LLMModelTag


class EmbeddingModelTagImportSerializer(BaseTagImportSerializer):
    class Meta(BaseTagImportSerializer.Meta):
        model = EmbeddingModelTag


class LLMConfigTagImportSerializer(BaseTagImportSerializer):
    class Meta(BaseTagImportSerializer.Meta):
        model = LLMConfigTag
