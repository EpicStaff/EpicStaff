from django_filters import rest_framework as filters
from tables.models.embedding_models import EmbeddingModel
from tables.models.llm_models import LLMModel
from tables.models.session_models import Session
from tables.models import Provider  # SourceCollection,


class CharInFilter(filters.BaseInFilter, filters.CharFilter):
    pass


class SessionFilter(filters.FilterSet):
    status = CharInFilter(field_name="status", lookup_expr="in")

    class Meta:
        model = Session
        fields = ["graph_id", "status"]


# class CollectionFilter(filters.FilterSet):
#     collection_id = filters.CharFilter(field_name="collection_id", lookup_expr="exact")

#     class Meta:
#         model = SourceCollection
#         fields = ["collection_id"]


class ProviderFilter(filters.FilterSet):
    model_type = filters.CharFilter(method="filter_by_model_type")

    class Meta:
        model = Provider
        fields = ["name", "model_type"]

    def filter_by_model_type(self, queryset, name, value):
        mapping = {
            "llm": "llmmodel",
            "embedding": "embeddingmodel",
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
