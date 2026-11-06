"""The knowledge role may read only some columns of the LLM and embedding config tables; the
ORM must map exactly those.

joinedload selects every mapped column, and Postgres checks column privileges on each of
them, so a column mapped but not granted fails every RAG config load with "permission
denied". A column granted but not mapped widens the role's access for nothing.
"""

import pytest
from infrastructure.database.models import EmbeddingConfig, LLMConfig, LLMModel
from src.django_app.tables.service_db_grants import KNOWLEDGE_GRANTS

UPDATE_CONTRACT = (
    "Keep the knowledge ORM model and KNOWLEDGE_GRANTS in "
    "src/django_app/tables/service_db_grants.py in step."
)


@pytest.mark.parametrize("orm_model", [EmbeddingConfig, LLMConfig, LLMModel])
def test_mapped_columns_are_exactly_the_granted_select_columns(orm_model):
    table_grant = next(
        (grant for grant in KNOWLEDGE_GRANTS.tables if grant.table == orm_model.__tablename__),
        None,
    )

    assert table_grant is not None, UPDATE_CONTRACT
    assert table_grant.privileges == (), (
        "A table-level privilege would expose every column. " + UPDATE_CONTRACT
    )
    # Database column names, not attribute names: the grant names what Postgres checks.
    mapped_columns = {column.name for column in orm_model.__table__.columns}
    assert mapped_columns == set(table_grant.select_columns), UPDATE_CONTRACT


@pytest.mark.parametrize("orm_model", [EmbeddingConfig, LLMConfig])
def test_config_never_maps_extra_headers(orm_model):
    assert "extra_headers" not in orm_model.__table__.columns
