from rest_framework import serializers

from tables.services.cdt_explain import SUPPORTED_BLOCK_TYPES

MAX_BLOCKS = 100


class CdtExplainRuleSerializer(serializers.Serializer):
    order = serializers.IntegerField()
    name = serializers.CharField(allow_blank=True)
    enabled = serializers.BooleanField(default=True)


class CdtExplainTableSerializer(serializers.Serializer):
    node_name = serializers.CharField(allow_blank=True)
    default_next_node = serializers.CharField(allow_null=True, required=False)
    error_next_node = serializers.CharField(allow_null=True, required=False)
    default_model = serializers.CharField(allow_blank=True, required=False)
    rules = CdtExplainRuleSerializer(many=True, required=False, default=list)


class CdtExplainBlockSerializer(serializers.Serializer):
    id = serializers.CharField()
    block = serializers.ChoiceField(choices=sorted(SUPPORTED_BLOCK_TYPES))

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("Each block must be an object.")
        validated = super().to_internal_value(data)
        return {**data, **validated}


class CdtExplainRequestSerializer(serializers.Serializer):
    llm_config = serializers.IntegerField()
    table = CdtExplainTableSerializer()
    blocks = serializers.ListField(
        child=CdtExplainBlockSerializer(), allow_empty=False, max_length=MAX_BLOCKS
    )

    def validate_blocks(self, blocks):
        ids = [block["id"] for block in blocks]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Block ids must be unique within a request.")
        return blocks


class CdtExplanationSerializer(serializers.Serializer):
    id = serializers.CharField()
    text = serializers.CharField()
    generated_by = serializers.CharField()


class CdtExplainFailureSerializer(serializers.Serializer):
    id = serializers.CharField()
    detail = serializers.CharField()


class CdtExplainResponseSerializer(serializers.Serializer):
    explanations = CdtExplanationSerializer(many=True)
    failures = CdtExplainFailureSerializer(many=True)
