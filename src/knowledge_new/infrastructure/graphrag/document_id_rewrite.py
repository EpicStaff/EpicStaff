from collections.abc import Mapping

import pyarrow as pa
import pyarrow.compute as pc
from domain.errors import InvalidArtifactArchiveError


class DocumentIdRewriter:
    """Replace old `GraphRagDocument` ids in GraphRAG tables with new ones.

    GraphRAG stores our `GraphRagDocument` ids inside its own tables
    (`documents.parquet:id`, `text_units.parquet:document_id`). A restored index
    belongs to new `GraphRagDocument` rows, so those ids must be changed to theirs,
    or a later re-index mistakes which documents it already holds.

    The lookup arrays are built once, so one rewriter can rewrite a large table
    batch by batch without rebuilding them per batch.

    Args:
        document_id_map: New `GraphRagDocument` id for each old one, keyed by the old
            id as text, as GraphRAG stores it. Keys of documents absent from a table
            are ignored: Django sends every document of the RAG, indexed or not. A
            key that is not text can match nothing, so it is left out.
    """

    def __init__(self, document_id_map: Mapping[str, int]):
        old_ids = [old_id for old_id in document_id_map if isinstance(old_id, str)]
        self._old_ids = pa.array(old_ids, type=pa.large_string())
        self._new_ids = pa.array(
            [str(document_id_map[old_id]) for old_id in old_ids], type=pa.large_string()
        )

    def rewrite(self, table: pa.Table, column: str) -> pa.Table:
        """Return `table` with every value of `column` replaced by its new document id.

        The column keeps its original type (GraphRAG writes `large_string`), and every
        other column is left as it is.

        Raises:
            InvalidArtifactArchiveError: If `column` is missing or holds no text, or a
                value of it is null or has no entry in the map. Nothing is changed
                then, so no old id survives silently.
        """
        position = table.schema.get_field_index(column)
        if position == -1:
            raise InvalidArtifactArchiveError(reason=f"Column '{column}' is missing.")
        field = table.schema.field(position)
        if not (pa.types.is_string(field.type) or pa.types.is_large_string(field.type)):
            raise InvalidArtifactArchiveError(reason=f"Column '{column}' does not hold text.")

        # Compared as large_string, the type of the lookup, so the map is never re-cast.
        values = table.column(position).cast(pa.large_string())
        # Null where a value is null or not in the map: skip_nulls keeps a null from
        # matching anything.
        positions = pc.index_in(values, options=pc.SetLookupOptions(self._old_ids, skip_nulls=True))
        if positions.null_count:
            unknown = pc.filter(values, pc.is_null(positions))[0].as_py()
            raise InvalidArtifactArchiveError(
                reason=f"Document ID {unknown} in column '{column}' not found in the provided mapping."
            )

        new_values = pc.take(self._new_ids, positions).cast(field.type)
        return table.set_column(position, field, new_values)


def rewrite_document_ids(
    table: pa.Table, column: str, document_id_map: Mapping[str, int]
) -> pa.Table:
    """Return `table` with every value of `column` replaced by its new document id.

    A one-off `DocumentIdRewriter(document_id_map).rewrite(table, column)`; see it
    for the rules and the errors raised.
    """
    return DocumentIdRewriter(document_id_map).rewrite(table, column)
