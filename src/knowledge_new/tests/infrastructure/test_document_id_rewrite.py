import io

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from domain.errors import InvalidArtifactArchiveError
from infrastructure.graphrag.document_id_rewrite import rewrite_document_ids


def _documents_table(document_ids: list[str | None]) -> pa.Table:
    """A `documents.parquet` shape: GraphRAG stores the id as `large_string`."""
    return pa.table(
        {
            "id": pa.array(document_ids, type=pa.large_string()),
            "title": [f"file_{index}.txt" for index in range(len(document_ids))],
        }
    )


def test_rewrites_every_document_id():
    result = rewrite_document_ids(_documents_table(["2", "3"]), "id", {"2": 51, "3": 52})

    assert result.column("id").to_pylist() == ["51", "52"]


def test_ignores_map_entries_of_documents_not_in_the_table():
    result = rewrite_document_ids(_documents_table(["2"]), "id", {"2": 51, "9": 99})

    assert result.column("id").to_pylist() == ["51"]


def test_rewrites_text_units_and_keeps_their_other_columns():
    text_units = pa.table(
        {
            "id": pa.array(["unit-a", "unit-b", "unit-c"], type=pa.large_string()),
            "document_id": pa.array(["2", "2", "3"], type=pa.large_string()),
            "entity_ids": pa.array([["entity-1"], [], ["entity-2", "entity-3"]]),
        }
    )

    result = rewrite_document_ids(text_units, "document_id", {"2": 51, "3": 52})

    assert result.column("document_id").to_pylist() == ["51", "51", "52"]
    assert result.column("id").to_pylist() == ["unit-a", "unit-b", "unit-c"]
    assert result.column("entity_ids").to_pylist() == [
        ["entity-1"],
        [],
        ["entity-2", "entity-3"],
    ]


def test_rewritten_table_keeps_large_string_after_a_parquet_round_trip():
    result = rewrite_document_ids(_documents_table(["2"]), "id", {"2": 51})
    buffer = io.BytesIO()
    pq.write_table(result, buffer)
    buffer.seek(0)

    read_back = pq.read_table(buffer)

    assert read_back.schema.field("id").type == pa.large_string()
    assert read_back.column("id").to_pylist() == ["51"]


@pytest.mark.parametrize(
    ("document_ids", "document_id_map"),
    [
        pytest.param(["2", "7"], {"2": 51}, id="id missing from the map"),
        pytest.param(["2", None], {"2": 51}, id="null id"),
        pytest.param(["2"], {}, id="empty map"),
        pytest.param(["2"], {2: 51}, id="map keyed by int instead of the stored text"),
    ],
)
def test_refuses_an_id_without_a_new_one(document_ids, document_id_map):
    with pytest.raises(InvalidArtifactArchiveError):
        rewrite_document_ids(_documents_table(document_ids), "id", document_id_map)


def test_empty_table_is_returned_unchanged():
    result = rewrite_document_ids(_documents_table([]), "id", {"2": 51})

    assert result.num_rows == 0
    assert result.schema.field("id").type == pa.large_string()
