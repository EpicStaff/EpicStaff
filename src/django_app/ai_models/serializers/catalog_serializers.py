from rest_framework import serializers

from ai_models.domain.specs import ModelKind


class CatalogKindQuerySerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[kind.value for kind in ModelKind])


class CatalogModelsQuerySerializer(CatalogKindQuerySerializer):
    provider = serializers.CharField()
    search = serializers.CharField(required=False, allow_blank=True, default="")


class CatalogSchemasQuerySerializer(CatalogKindQuerySerializer):
    provider = serializers.CharField()
    model = serializers.CharField()


class CatalogProviderSerializer(serializers.Serializer):
    name = serializers.CharField()
    label = serializers.CharField()
    recommended = serializers.BooleanField()
    custom_models = serializers.BooleanField()


class CatalogModelSerializer(serializers.Serializer):
    name = serializers.CharField()
    recommended = serializers.BooleanField()
    deprecation_date = serializers.DateField(allow_null=True)
    limits = serializers.DictField()
