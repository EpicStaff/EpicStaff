import pytest
from presentation.rest.schemas import IndexEstimateInputSchema
from pydantic import ValidationError


def test_index_config_is_optional():
    schema = IndexEstimateInputSchema.model_validate({"document_ids": [1]})

    assert schema.index_config is None


def test_index_config_accepts_estimate_fields():
    schema = IndexEstimateInputSchema.model_validate(
        {"document_ids": [1], "index_config": {"chunk_size": 300, "max_gleanings": 2}}
    )

    assert schema.index_config.chunk_size == 300
    assert schema.index_config.chunk_overlap is None
    assert schema.index_config.max_gleanings == 2


def test_index_config_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        IndexEstimateInputSchema.model_validate(
            {"document_ids": [1], "index_config": {"not_a_setting": 1}}
        )
