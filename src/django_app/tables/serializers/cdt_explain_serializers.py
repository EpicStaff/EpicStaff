from rest_framework import serializers
from tables.constants.cdt_explanation_limits import (
    MAX_EXPLANATION_TEXT_LENGTH,
    MAX_FINGERPRINT_LENGTH,
    MAX_GENERATED_BY_LENGTH,
    MAX_STORED_EXPLANATIONS,
    MAX_STORED_EXPLANATIONS_BYTES,
)
from tables.services.cdt_explain import SUPPORTED_BLOCK_TYPES
from tables.validators.cdt_explanations import review_explanations

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


class CdtStoredExplanationSerializer(serializers.Serializer):
    """The shape of one stored explanation, for the API schema.

    Validation is `review_explanations`, which every writer shares; this only
    describes the result.
    """

    text = serializers.CharField(max_length=MAX_EXPLANATION_TEXT_LENGTH)
    # camelCase is the stored key the frontend reads back, not a Python name.
    generatedBy = serializers.CharField(max_length=MAX_GENERATED_BY_LENGTH)  # noqa: N815
    fingerprint = serializers.CharField(max_length=MAX_FINGERPRINT_LENGTH)


class CdtStoredExplanationsField(serializers.DictField):
    """A node's whole `metadata["explanations"]`, validated strictly.

    Refuses any map `review_explanations` would not keep whole.
    """

    default_error_messages = {
        "too_many": "At most {max_count} explanations can be stored on a node.",
        "too_large": "Explanations may take at most {max_bytes} bytes in total.",
    }

    def __init__(self, **kwargs):
        super().__init__(child=CdtStoredExplanationSerializer(), **kwargs)

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            self.fail("not_a_dict", input_type=type(data).__name__)
        # Checked up front so an oversized map is refused before any entry is examined.
        if len(data) > MAX_STORED_EXPLANATIONS:
            self.fail("too_many", max_count=MAX_STORED_EXPLANATIONS)

        review = review_explanations(data, collect_errors=True)
        if review.errors:
            raise serializers.ValidationError(review.errors)
        if review.over_limit:
            self.fail("too_large", max_bytes=MAX_STORED_EXPLANATIONS_BYTES)
        return review.kept


class CdtExplanationsSaveRequestSerializer(serializers.Serializer):
    save_version = serializers.IntegerField()
    explanations = CdtStoredExplanationsField()


class CdtExplanationsSaveResponseSerializer(serializers.Serializer):
    explanations = CdtStoredExplanationsField()
    save_version = serializers.IntegerField()
