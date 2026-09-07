import pytest

from tables.serializers.model_serializers.embedding_serializers import (
    EmbeddingModelSerializer,
)
from tables.serializers.model_serializers.llm_serializers import (
    LLMModelSerializer,
    RealtimeModelSerializer,
    RealtimeTranscriptionModelSerializer,
)

# Read off the serializers as they stand before the refactor. Switching from
# fields="__all__" to an explicit list must not change the wire contract.
EXPECTED_FIELDS = {
    LLMModelSerializer: [
        "id",
        "capabilities",
        "name",
        "predefined",
        "description",
        "deployment_id",
        "api_version",
        "base_url",
        "is_visible",
        "is_custom",
        "org",
        "created_by",
        "llm_provider",
        "tags",
    ],
    RealtimeModelSerializer: [
        "id",
        "name",
        "is_custom",
        "org",
        "created_by",
        "provider",
    ],
    RealtimeTranscriptionModelSerializer: [
        "id",
        "name",
        "is_custom",
        "org",
        "created_by",
        "provider",
    ],
    EmbeddingModelSerializer: [
        "id",
        "tags",
        "name",
        "predefined",
        "deployment",
        "base_url",
        "is_visible",
        "is_custom",
        "org",
        "created_by",
        "embedding_provider",
    ],
}


@pytest.mark.parametrize("serializer_class", list(EXPECTED_FIELDS))
def test_wire_field_set_is_unchanged(serializer_class):
    assert set(serializer_class().fields) == set(EXPECTED_FIELDS[serializer_class])


@pytest.mark.parametrize("serializer_class", list(EXPECTED_FIELDS))
def test_ownership_flags_are_read_only(serializer_class):
    """is_custom and predefined decide whether a row is a shared built-in, so the
    client must never set them; the viewset's custom_create_values does."""
    fields = serializer_class().fields
    assert fields["is_custom"].read_only is True
    if "predefined" in fields:
        assert fields["predefined"].read_only is True


@pytest.mark.parametrize("serializer_class", list(EXPECTED_FIELDS))
def test_org_and_created_by_stay_read_only(serializer_class):
    fields = serializer_class().fields
    assert fields["org"].read_only is True
    assert fields["created_by"].read_only is True
