from collections.abc import Mapping

import pyarrow as pa
from domain.errors import InvalidArtifactArchiveError


def rewrite_document_ids(
    table: pa.Table, column: str, document_id_map: Mapping[str, int]
) -> pa.Table:
    """Return `table` with every value of `column` replaced by its new document id.

    GraphRAG stores our `GraphRagDocument` ids inside its own tables
    (`documents.parquet:id`, `text_units.parquet:document_id`). A restored index
    belongs to new `GraphRagDocument` rows, so those ids must be changed to theirs,
    or a later re-index mistakes which documents it already holds.

    The column keeps its original type (GraphRAG writes `large_string`), and every
    other column is left as it is.

    Args:
        table: A GraphRAG table read from the restored index.
        column: Name of the column holding document ids.
        document_id_map: New `GraphRagDocument` id for each old one, keyed by the old
            id as text, as GraphRAG stores it. Keys of documents absent from `table`
            are ignored: Django sends every document of the RAG, indexed or not.

    Raises:
        InvalidArtifactArchiveError: If a value of `column` is null or has no entry in
            `document_id_map`. Nothing is changed then, so no old id survives silently.
    """
    old_ids = table[column].to_pylist()
    for old_id in old_ids:
        if old_id is None or old_id not in document_id_map:
            raise InvalidArtifactArchiveError(
                reason=f"Document ID {old_id} in column '{column}' not found in the provided mapping."
            )

    new_ids = [str(document_id_map[old_id]) for old_id in old_ids]

    field = table.schema.field(column)
    new_array = pa.array(new_ids, type=field.type)
    return table.set_column(table.schema.get_field_index(column), field, new_array)
