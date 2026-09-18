from rest_framework import serializers

from tables.models.tag_models import (
    EmbeddingConfigTag,
    EmbeddingModelTag,
    GraphTag,
    LLMConfigTag,
    LLMModelTag,
)


class LLMModelTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = LLMModelTag
        fields = ("id", "name", "predefined")
        read_only_fields = ("predefined",)


class EmbeddingTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmbeddingModelTag
        fields = ("id", "name", "predefined")
        read_only_fields = ("predefined",)


class LLMConfigTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = LLMConfigTag
        fields = ("id", "name", "predefined")
        read_only_fields = ("predefined",)


class EmbeddingConfigTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmbeddingConfigTag
        fields = ("id", "name", "predefined")
        read_only_fields = ("predefined",)


class GraphTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = GraphTag
        fields = "__all__"
