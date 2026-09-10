from typing import get_args

from rest_framework import serializers

from src.shared.models.search_config_suggestion import GraphSearchMethod


GRAPH_SEARCH_METHODS = get_args(GraphSearchMethod)


class SuggestCollectionMetricsSerializer(serializers.Serializer):
    total_documents = serializers.IntegerField(min_value=0)
    total_chunks = serializers.IntegerField(min_value=0)
    avg_chunk_size = serializers.FloatField(min_value=0)


class NaiveRagSuggestInputSerializer(serializers.Serializer):
    knowledge_collection_id = serializers.IntegerField(min_value=1)
    llm_config_id = serializers.IntegerField(min_value=1)
    user_custom_params = serializers.DictField(required=False, allow_null=True)


class GraphRagSuggestInputSerializer(serializers.Serializer):
    knowledge_collection_id = serializers.IntegerField(min_value=1)
    search_method = serializers.ChoiceField(
        choices=GRAPH_SEARCH_METHODS,
        help_text="Graph RAG search method to tune.",
    )
    llm_config_id = serializers.IntegerField(min_value=1)
    user_custom_params = serializers.DictField(required=False, allow_null=True)


class SuggestOutputSerializer(serializers.Serializer):
    metrics = SuggestCollectionMetricsSerializer()
    resolved_llm_name = serializers.CharField(allow_null=True, allow_blank=True)
    llm_resolution_warning = serializers.CharField(allow_null=True, allow_blank=True)
    effective_llm_context_window = serializers.IntegerField(min_value=1)
    safe_token_budget = serializers.IntegerField(min_value=1)
    clamped_fields = serializers.ListField(child=serializers.CharField())
    suggested_params = serializers.DictField()
    recommended_search_method = serializers.ChoiceField(
        choices=GRAPH_SEARCH_METHODS, required=False, allow_null=True
    )
