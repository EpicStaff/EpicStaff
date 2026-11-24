from django_filters import rest_framework as filters

from ai_models.domain.specs import ModelKind
from ai_models.models import EmbeddingModel, LLMModel, Provider
from ai_models.repository import CatalogRepository


class ProviderFilter(filters.FilterSet):
    model_type = filters.CharFilter(method="filter_by_model_type")

    class Meta:
        model = Provider
        fields = ["name", "model_type"]

    def filter_by_model_type(self, queryset, name, value):
        if value in (ModelKind.LLM, ModelKind.EMBEDDING):
            # Rows may store a catalog provider under an alias (google_ai for gemini).
            provider_names = {
                provider_name
                for provider in CatalogRepository.default().providers(ModelKind(value))
                for provider_name in (provider.name, *provider.aliases)
            }
            return queryset.filter(name__in=provider_names)

        mapping = {
            "realtime": "realtimemodel",
            "transcription": "realtimetranscriptionmodel",
        }

        relation = mapping.get(value)
        if relation:
            return queryset.filter(**{f"{relation}__isnull": False}).distinct()

        return queryset


class BaseTagFilter(filters.FilterSet):
    tags = filters.CharFilter(method="filter_by_tags")

    def filter_by_tags(self, queryset, name, value):
        tag_names = [tag.strip() for tag in value.split(",") if tag.strip()]

        if not tag_names:
            return queryset

        return queryset.filter(tags__name__in=tag_names).distinct()


class LLMModelFilter(BaseTagFilter):
    class Meta:
        model = LLMModel

        fields = {
            "name": ["exact", "icontains"],
            "llm_provider": ["exact"],
            "predefined": ["exact"],
            "is_visible": ["exact"],
        }


class EmbeddingModelFilter(BaseTagFilter):
    class Meta:
        model = EmbeddingModel
        fields = {
            "name": ["exact", "icontains"],
            "embedding_provider": ["exact"],
            "predefined": ["exact"],
            "is_visible": ["exact"],
        }
