from collections.abc import Iterable

from rbac.authorship import record_last_edits
from tables.models import SourceCollection


def record_collection_edits(collection_ids: Iterable[int | None], user: object | None) -> None:
    """Record `user` as the last editor of the collections, in one statement.

    Changing a collection's documents or RAG settings edits the collection. Without an
    acting user (system and background writers) nothing is recorded.
    """
    if user is None:
        return
    ids = {collection_id for collection_id in collection_ids if collection_id is not None}
    if ids:
        record_last_edits(SourceCollection.objects.filter(collection_id__in=ids), user)
