"""
Regression test for the concurrent-update race on Surface content rows.

SurfaceContentService.replace_* does delete-all + re-create of child rows
(knowledge, python_tools, mcp_tools, storage_items). Two concurrent PUT/PATCH
requests for the SAME surface used to race: TX-B's DELETE blocks on TX-A's
locks, then after A commits, B's snapshot can no longer see A's rows, so B's
DELETE removes nothing and its INSERTs collide with A's rows on the
`uniq_surface_knowledge` unique constraint -> IntegrityError (500).

Fix: SurfaceService.update_surface takes a row lock on the Surface
(`select_for_update`) at the top of its atomic block, serializing concurrent
writers to the same surface.
"""

import threading

import pytest
from django.db import IntegrityError

from agents.models.surface_models import Surface, SurfaceKnowledge
from agents.services.surface_service import SurfaceService
from tables.models.knowledge_models.collection_models import (
    BaseRagType,
    SourceCollection,
)
from tables.models.rbac_models import Organization


def _make_naive_collection(name, org):
    collection = SourceCollection.objects.create(collection_name=name, org=org)
    BaseRagType.objects.create(
        rag_type=BaseRagType.RagType.NAIVE,
        source_collection=collection,
    )
    return collection


@pytest.mark.django_db(transaction=True)
def test_concurrent_update_surface_does_not_raise_integrity_error():
    """Two threads updating the same surface's knowledge concurrently must
    serialize (via the surface row lock) instead of racing on
    delete-then-recreate, so no IntegrityError is raised and the final rows
    equal exactly one of the two submitted lists."""
    org = Organization.objects.create(name="concurrency-org")
    surface = Surface.objects.create(organization=org, name="concurrency-surface")

    shared_collection = _make_naive_collection("shared-coll", org)
    collection_a = _make_naive_collection("coll-a", org)
    collection_b = _make_naive_collection("coll-b", org)

    knowledge_list_a = [
        {
            "collection": shared_collection,
            "naive_search_config": None,
            "graph_basic_search_config": None,
            "graph_local_search_config": None,
        },
        {
            "collection": collection_a,
            "naive_search_config": None,
            "graph_basic_search_config": None,
            "graph_local_search_config": None,
        },
    ]
    knowledge_list_b = [
        {
            "collection": shared_collection,
            "naive_search_config": None,
            "graph_basic_search_config": None,
            "graph_local_search_config": None,
        },
        {
            "collection": collection_b,
            "naive_search_config": None,
            "graph_basic_search_config": None,
            "graph_local_search_config": None,
        },
    ]

    start_barrier = threading.Barrier(2)
    errors = []

    def run_update(knowledge_data):
        from django.db import connections

        try:
            start_barrier.wait(timeout=5)
            SurfaceService.update_surface(
                instance=surface,
                validated_data={"knowledge": knowledge_data},
                partial=True,
            )
        except Exception as exc:  # noqa: BLE001 - captured for main-thread assertion
            errors.append(exc)
        finally:
            connections.close_all()

    thread_a = threading.Thread(target=run_update, args=(knowledge_list_a,))
    thread_b = threading.Thread(target=run_update, args=(knowledge_list_b,))

    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=10)
    thread_b.join(timeout=10)

    integrity_errors = [exc for exc in errors if isinstance(exc, IntegrityError)]
    assert (
        not integrity_errors
    ), f"IntegrityError raised under concurrency: {integrity_errors}"
    assert not errors, f"Unexpected error(s) under concurrency: {errors}"

    final_collection_ids = set(
        SurfaceKnowledge.objects.filter(surface=surface).values_list(
            "collection_id", flat=True
        )
    )
    expected_a = {shared_collection.collection_id, collection_a.collection_id}
    expected_b = {shared_collection.collection_id, collection_b.collection_id}

    assert final_collection_ids in (expected_a, expected_b), (
        f"Final knowledge {final_collection_ids} is neither submitted list "
        f"(last-writer-wins expected {expected_a} or {expected_b})"
    )
