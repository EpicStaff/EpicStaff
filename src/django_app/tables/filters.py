from django.db.models import OuterRef, Exists
from django_filters import rest_framework as filters
from tables.models import GraphSessionMessage
from rest_framework.filters import BaseFilterBackend
from tables.models.embedding_models import EmbeddingModel
from tables.models.llm_models import LLMModel
from tables.models.session_models import Session
from tables.models import Provider  # SourceCollection,


class CharInFilter(filters.BaseInFilter, filters.CharFilter):
    pass


class LabelFilterBackend(BaseFilterBackend):
    """
    Filters graphs by label_id (repeatable). Each label_id includes its full
    subtree of descendants. Multiple label_ids use OR logic.
    Example: ?label_id=1&label_id=3

    Use ?no_label=true to return only graphs with no labels assigned.
    """

    def filter_queryset(self, request, queryset, view):
        from tables.utils.helpers import get_label_descendant_ids

        no_label = request.query_params.get("no_label", "").lower() in ("true", "1")
        label_ids = request.query_params.getlist("label_id")

        if no_label:
            return queryset.filter(labels__isnull=True).distinct()

        if not label_ids:
            return queryset
        all_ids: set[int] = set()
        for lid in label_ids:
            all_ids |= get_label_descendant_ids(int(lid))
        return queryset.filter(labels__in=all_ids).distinct()

    def get_schema_operation_parameters(self, view):
        return [
            {
                "name": "label_id",
                "required": False,
                "in": "query",
                "description": (
                    "Filter by label ID (includes all descendants). "
                    "Repeat to filter by multiple labels (OR logic)."
                ),
                "schema": {"type": "integer"},
            },
            {
                "name": "no_label",
                "required": False,
                "in": "query",
                "description": "If true, return only graphs with no labels.",
                "schema": {"type": "boolean"},
            },
        ]


class SessionFilter(filters.FilterSet):
    status = CharInFilter(field_name="status", lookup_expr="in")
    node_name = filters.CharFilter(
        field_name="graphsessionmessage__name", lookup_expr="exact", distinct=True
    )
    graph_name = filters.CharFilter(field_name="graph__name", lookup_expr="iexact")
    is_error_cause = filters.BooleanFilter(method="filter_by_error_cause")

    class Meta:
        model = Session
        fields = ["graph_id", "graph_name", "status", "node_name"]

    def filter_by_error_cause(self, queryset, name, value):
        """Returns sessions that finished with error on specific node"""
        if not value:
            return queryset

        node_name = self.data.get("node_name")

        messages = GraphSessionMessage.objects.filter(
            session=OuterRef("pk"), message_data__message_type="error"
        )
        if node_name:
            messages = messages.filter(name=node_name)

        return queryset.filter(Exists(messages)).distinct()


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
