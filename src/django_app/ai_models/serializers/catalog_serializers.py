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


class CatalogFavoriteQuerySerializer(serializers.Serializer):
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
    # Catalog models carry no `custom` attribute; DRF falls back to the default for them.
    custom = serializers.BooleanField(read_only=True, default=False)
    is_favorite = serializers.SerializerMethodField()

    def get_is_favorite(self, model) -> bool:
        """The caller starred the model; the view passes the starred names as `favorite_names`."""
        name = model["name"] if isinstance(model, dict) else model.name
        return name in self.context.get("favorite_names", ())
