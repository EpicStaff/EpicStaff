from collections.abc import Iterable

from rbac.authorship import record_last_edits
from src.shared.models import UserAction
from tables.models import SourceCollection
from user_audit.context import mark_request_handled
from user_audit.recorder import record_user_action


def record_collection_edits(collection_ids: Iterable[int | None], user: object | None) -> None:
    """Record `user` as the last editor of the collections, in one statement.

    Changing a collection's documents or RAG settings edits the collection. Without an
    acting user (system and background writers) nothing is recorded.
    """
    ids = {collection_id for collection_id in collection_ids if collection_id is not None}
    if ids:
        record_last_edits(SourceCollection.objects.filter(collection_id__in=ids), user)


def record_rag_change(collection: SourceCollection, *, changed: bool) -> None:
    """Record the collection as updated when its RAG settings, chunks or index changed.

    A RAG config and its document configs have no name a reader knows them by, so the
    change is recorded on the collection they belong to. When nothing changed, the request
    is marked handled instead, so the middleware's fallback records nothing either.
    """
    if changed:
        record_user_action(action=UserAction.UPDATED, org_id=collection.org_id, target=collection)
    else:
        mark_request_handled()
