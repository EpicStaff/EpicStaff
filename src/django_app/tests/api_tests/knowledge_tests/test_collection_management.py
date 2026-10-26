"""The source-collection endpoints: CRUD, bulk delete, copy, soft delete, authorship.

Cross-org access is covered in test_org_scoping_knowledge.py.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status

from tables.models import DocumentMetadata
from tables.models.knowledge_models import SourceCollection

MISSING = 99999


@pytest.mark.django_db
def test_list_shows_each_collection_with_its_summary(auth_client, source_collection, empty_collection):
    response = auth_client.get(reverse("sourcecollection-list"))

    assert response.status_code == status.HTTP_200_OK
    assert {item["collection_id"] for item in response.json()} == {
        source_collection.collection_id, empty_collection.collection_id
    }
    assert all({"collection_name", "description", "document_count"} <= item.keys() for item in response.json())


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("body", "expected_name", "expected_description"),
    [
        ({"collection_name": "My New Collection"}, "My New Collection", None),
        ({"collection_name": ""}, "Untitled Collection", None),
        (
            {"collection_name": "Documented", "description": "Contains onboarding docs for new hires."},
            "Documented",
            "Contains onboarding docs for new hires.",
        ),
    ],
    ids=["named", "blank-name-gets-default", "with-description"],
)
def test_create(auth_client, body, expected_name, expected_description):
    response = auth_client.post(reverse("sourcecollection-list"), body, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    collection = SourceCollection.objects.get(collection_id=response.json()["collection_id"])
    assert (response.json()["collection_name"], collection.collection_name) == (expected_name, expected_name)
    assert response.json()["status"] == "empty"
    if expected_description is not None:
        assert collection.description == response.json()["description"] == expected_description


@pytest.mark.django_db
def test_a_taken_name_is_numbered_not_rejected(auth_client, source_collection):
    names = [
        auth_client.post(
            reverse("sourcecollection-list"), {"collection_name": source_collection.collection_name}, format="json"
        ).json()["collection_name"]
        for _ in range(2)
    ]

    assert names == [f"{source_collection.collection_name} (1)", f"{source_collection.collection_name} (2)"]


@pytest.mark.django_db
def test_read_and_update(auth_client, source_collection):
    url = reverse("sourcecollection-detail", args=[source_collection.collection_id])

    read = auth_client.get(url)
    updated = auth_client.patch(url, {"collection_name": "Updated Name", "description": "Updated description."}, format="json")

    assert read.status_code == status.HTTP_200_OK
    assert (read.json()["collection_name"], read.json()["description"]) == (
        source_collection.collection_name, source_collection.description
    )
    assert updated.status_code == status.HTTP_200_OK
    source_collection.refresh_from_db()
    assert (source_collection.collection_name, source_collection.description) == ("Updated Name", "Updated description.")


@pytest.mark.django_db
@pytest.mark.parametrize("write", ["create", "update"])
@pytest.mark.parametrize(
    ("description", "expected"),
    [
        # No NUL here: DRF rejects it before cleaning runs.
        ("\x1b[2JIgnore\x07 previous\nrules\tnow\x7f\r\n", "[2JIgnore previous rules now"),
        ("x" * 2000 + "\x07" * 5, "x" * 2000),
    ],
    ids=["control-chars-cleaned", "at-limit-once-cleaned"],
)
def test_description_is_stored_without_control_chars(auth_client, source_collection, write, description, expected):
    if write == "create":
        response = auth_client.post(
            reverse("sourcecollection-list"), {"collection_name": "Described", "description": description}, format="json"
        )
    else:
        response = auth_client.patch(
            reverse("sourcecollection-detail", args=[source_collection.collection_id]),
            {"description": description},
            format="json",
        )

    assert response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED), response.content
    stored = SourceCollection.objects.get(collection_id=response.json()["collection_id"])
    assert stored.description == response.json()["description"] == expected


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("write", "body"),
    [
        ("create", {"collection_name": "Overlong", "description": "x" * 2001}),
        ("update", {"description": "x" * 2001}),
        ("update", {"collection_name": ""}),
    ],
    ids=["create-description-too-long", "update-description-too-long", "update-blank-name"],
)
def test_invalid_write_is_400_and_stores_nothing(auth_client, source_collection, write, body):
    before = list(SourceCollection.objects.values_list("collection_id", "collection_name", "description"))
    if write == "create":
        response = auth_client.post(reverse("sourcecollection-list"), body, format="json")
    else:
        response = auth_client.patch(
            reverse("sourcecollection-detail", args=[source_collection.collection_id]), body, format="json"
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert list(SourceCollection.objects.values_list("collection_id", "collection_name", "description")) == before


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "route"),
    [("get", "sourcecollection-detail"), ("patch", "sourcecollection-detail"), ("delete", "sourcecollection-detail"), ("post", "sourcecollection-copy")],
)
def test_unknown_collection_is_404(auth_client, method, route):
    response = getattr(auth_client, method)(reverse(route, args=[MISSING]), {"collection_name": "x"}, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
@pytest.mark.parametrize("with_documents", [False, True])
def test_delete_removes_the_collection_and_its_documents(auth_client, source_collection, multiple_documents, empty_collection, with_documents):
    collection = source_collection if with_documents else empty_collection

    response = auth_client.delete(reverse("sourcecollection-detail", args=[collection.collection_id]))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["deleted_documents"] == (3 if with_documents else 0)
    assert not SourceCollection.objects.filter(collection_id=collection.collection_id).exists()
    assert DocumentMetadata.objects.filter(document_id__in=[d.document_id for d in multiple_documents]).exists() is not with_documents


@pytest.mark.django_db
def test_bulk_delete_counts_collections_and_skips_unknown_ids(
    auth_client, source_collection, empty_collection, multiple_documents
):
    ids = [source_collection.collection_id, empty_collection.collection_id]

    response = auth_client.post(reverse("sourcecollection-bulk-delete"), {"collection_ids": [*ids, MISSING]}, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    # The count is of collections, not of the rows their delete cascaded to.
    assert response.json()["deleted_count"] == 2
    assert response.json()["message"] == "Successfully deleted 2 collection(s)"
    assert response.json()["deleted_documents"] == len(multiple_documents)
    assert SourceCollection.deleted_objects.filter(collection_id__in=ids).count() == 2
    assert not DocumentMetadata.objects.filter(document_id__in=[d.document_id for d in multiple_documents]).exists()


@pytest.mark.django_db
def test_bulk_delete_without_ids_is_400(auth_client):
    response = auth_client.post(reverse("sourcecollection-bulk-delete"), {"collection_ids": []}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("body", "expected_name"),
    [({"new_collection_name": "Copied Collection"}, "Copied Collection"), ({}, "Test Collection (Copy)")],
    ids=["named", "default-name"],
)
def test_copy_duplicates_documents_and_description(auth_client, source_collection, multiple_documents, body, expected_name):
    source_collection.description = "Source description."
    source_collection.save()

    response = auth_client.post(reverse("sourcecollection-copy", args=[source_collection.collection_id]), body, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    copy = response.json()["collection"]
    assert (copy["collection_name"], copy["description"]) == (expected_name, "Source description.")
    assert DocumentMetadata.objects.filter(source_collection_id=copy["collection_id"]).count() == len(multiple_documents)



@pytest.mark.django_db
class TestCollectionSoftDelete:
    """Deleting a SourceCollection moves it to the recycle bin; purge removes it for good."""

    def _create_collection(self, auth_client, name):
        url = reverse("sourcecollection-list")
        response = auth_client.post(url, {"collection_name": name}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.content
        return response.json()

    def test_delete_collection_default_soft_deletes(self, auth_client):
        """DELETE hides the collection from `objects` but keeps it in
        `all_objects` with `active=False` and `soft_deleted_at` set."""
        collection = self._create_collection(auth_client, "Soft Delete Me")
        collection_id = collection["collection_id"]

        detail_url = reverse("sourcecollection-detail", args=[collection_id])
        delete_response = auth_client.delete(detail_url)
        assert (
            delete_response.status_code == status.HTTP_200_OK
        ), delete_response.content

        get_response = auth_client.get(detail_url)
        assert get_response.status_code == status.HTTP_404_NOT_FOUND

        assert not SourceCollection.objects.filter(collection_id=collection_id).exists()
        assert SourceCollection.all_objects.filter(collection_id=collection_id).exists()
        deleted = SourceCollection.all_objects.get(collection_id=collection_id)
        assert deleted.active is False
        assert deleted.soft_deleted_at is not None

    def test_purge_removes_binned_collection_documents_and_unshared_content(
        self, auth_client
    ):
        """purge_collection() removes the binned collection, its binned
        documents and the content no other document uses. Content that another
        collection uses survives, even while that collection is in the bin
        too, because a restore of it would need the content."""
        from tables.models import DocumentContent, DocumentMetadata
        from tables.services.knowledge_services.collection_management_service import (
            CollectionManagementService,
        )

        collection = SourceCollection.objects.get(
            collection_id=self._create_collection(auth_client, "Purge Me")["collection_id"]
        )
        other_collection = SourceCollection.objects.get(
            collection_id=self._create_collection(auth_client, "Keeps Shared")["collection_id"]
        )
        own_content = DocumentContent.objects.create(content=b"only mine")
        shared_content = DocumentContent.objects.create(content=b"shared")
        own_document = DocumentMetadata.objects.create(
            source_collection=collection, document_content=own_content,
            file_name="own.txt", file_type="txt", file_size=9,
        )
        DocumentMetadata.objects.create(
            source_collection=collection, document_content=shared_content,
            file_name="shared.txt", file_type="txt", file_size=6,
        )
        DocumentMetadata.objects.create(
            source_collection=other_collection, document_content=shared_content,
            file_name="shared.txt", file_type="txt", file_size=6,
        )
        collection.delete()
        other_collection.delete()

        summary = CollectionManagementService.purge_collection(
            SourceCollection.all_objects.get(collection_id=collection.collection_id)
        )

        assert summary == {
            "collection_id": collection.collection_id,
            "collection_name": "Purge Me",
            "deleted_documents": 2,
            "deleted_content": 1,
        }
        assert not SourceCollection.all_objects.filter(collection_id=collection.collection_id).exists()
        assert not DocumentMetadata.all_objects.filter(document_id=own_document.document_id).exists()
        assert not DocumentContent.objects.filter(id=own_content.id).exists()
        assert DocumentContent.objects.filter(id=shared_content.id).exists()

    def test_create_collection_with_name_of_soft_deleted_collection_keeps_name(
        self, auth_client
    ):
        """The (org, collection_name) unique constraint only applies to active
        rows — soft-deleting a collection must free its name for reuse without
        triggering the model's auto-rename-on-collision logic."""
        first = self._create_collection(auth_client, "Reusable Name")
        detail_url = reverse("sourcecollection-detail", args=[first["collection_id"]])
        delete_response = auth_client.delete(detail_url)
        assert delete_response.status_code == status.HTTP_200_OK

        second = self._create_collection(auth_client, "Reusable Name")

        # The dedup logic in SourceCollection.save() only checks `objects`
        # (active rows), so the soft-deleted collection's name doesn't collide.
        assert second["collection_name"] == "Reusable Name"

    def test_delete_collection_with_soft_delete_leaves_documents_intact(
        self, auth_client
    ):
        """Deleting a collection bins its documents with it but keeps their
        DocumentContent, so a restore brings everything back."""
        from tables.models import DocumentContent, DocumentMetadata

        collection = self._create_collection(auth_client, "Collection With Docs")
        collection_id = collection["collection_id"]
        source_collection = SourceCollection.objects.get(collection_id=collection_id)

        content = DocumentContent.objects.create(content=b"keep me")
        document = DocumentMetadata.objects.create(
            source_collection=source_collection,
            document_content=content,
            file_name="keep_me.txt",
            file_type="txt",
            file_size=8,
        )

        detail_url = reverse("sourcecollection-detail", args=[collection_id])
        delete_response = auth_client.delete(detail_url)
        assert (
            delete_response.status_code == status.HTTP_200_OK
        ), delete_response.content

        assert DocumentContent.objects.filter(id=content.id).exists()
        assert DocumentMetadata.deleted_objects.filter(
            document_id=document.document_id
        ).exists()


@pytest.mark.django_db
class TestCollectionBulkDeleteSoftDelete:
    """Bulk-deleting collections moves each one to the recycle bin."""

    def _create_collection(self, auth_client, name):
        url = reverse("sourcecollection-list")
        response = auth_client.post(url, {"collection_name": name}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.content
        return response.json()

    def test_bulk_delete_soft_deletes_collections_and_leaves_documents_intact(
        self, auth_client
    ):
        """Bulk-delete soft-deletes every collection via a per-instance
        `.delete()` loop (so `DeleteService` runs for each one) and leaves
        associated documents untouched."""
        from tables.models import DocumentContent, DocumentMetadata

        first = self._create_collection(auth_client, "Bulk Soft 1")
        second = self._create_collection(auth_client, "Bulk Soft 2")

        first_collection = SourceCollection.objects.get(
            collection_id=first["collection_id"]
        )
        content = DocumentContent.objects.create(content=b"bulk keep me")
        document = DocumentMetadata.objects.create(
            source_collection=first_collection,
            document_content=content,
            file_name="bulk_keep_me.txt",
            file_type="txt",
            file_size=12,
        )

        url = reverse("sourcecollection-bulk-delete")
        response = auth_client.post(
            url,
            {"collection_ids": [first["collection_id"], second["collection_id"]]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["deleted_count"] == 2

        for collection_id in (first["collection_id"], second["collection_id"]):
            assert not SourceCollection.objects.filter(
                collection_id=collection_id
            ).exists()
            deleted = SourceCollection.all_objects.get(collection_id=collection_id)
            assert deleted.active is False
            assert deleted.soft_deleted_at is not None

        assert DocumentContent.objects.filter(id=content.id).exists()
        assert DocumentMetadata.deleted_objects.filter(
            document_id=document.document_id
        ).exists()


@pytest.mark.django_db
class TestCollectionAuthorship:
    """SourceCollection records the acting user in created_by."""

    def test_create_authors_collection_with_request_user(self, auth_client, regular_user):
        response = auth_client.post(
            reverse("sourcecollection-list"),
            {"collection_name": "Authored"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        collection = SourceCollection.objects.get(pk=response.json()["collection_id"])
        assert collection.created_by == regular_user

    def test_user_id_absent_from_responses_and_ignored_on_create(
        self, auth_client, regular_user
    ):
        response = auth_client.post(
            reverse("sourcecollection-list"),
            {"collection_name": "Ignored", "user_id": "spoofed"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert "user_id" not in response.json()
        collection = SourceCollection.objects.get(pk=response.json()["collection_id"])
        assert not hasattr(collection, "user_id")
        assert collection.created_by == regular_user

        detail = auth_client.get(
            reverse("sourcecollection-detail", args=[collection.pk])
        ).json()
        listing = auth_client.get(reverse("sourcecollection-list")).json()
        assert "user_id" not in detail
        assert all("user_id" not in item for item in listing)

    def test_created_by_is_read_only_and_exposed(self, auth_client, regular_user):
        other = get_user_model().objects.create_user(
            email="other@example.com", password="OtherStrongPass123!"
        )
        response = auth_client.post(
            reverse("sourcecollection-list"),
            {"collection_name": "Spoof", "created_by": other.pk},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["created_by"] == {
            "id": regular_user.pk,
            "display_name": regular_user.display_name,
            "avatar_url": None,
        }

    def test_patch_leaves_null_author_null(self, auth_client, source_collection):
        assert source_collection.created_by is None

        response = auth_client.patch(
            reverse("sourcecollection-detail", args=[source_collection.pk]),
            {"description": "edited"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["created_by"] is None
        source_collection.refresh_from_db()
        assert source_collection.description == "edited"
        assert source_collection.created_by is None

    def test_patch_keeps_existing_author(self, auth_client, source_collection):
        original_author = get_user_model().objects.create_user(
            email="author@example.com", password="AuthorStrongPass123!"
        )
        source_collection.created_by = original_author
        source_collection.save()

        response = auth_client.patch(
            reverse("sourcecollection-detail", args=[source_collection.pk]),
            {"description": "edited"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        source_collection.refresh_from_db()
        assert source_collection.created_by == original_author

    def test_copy_is_authored_by_actor(self, auth_client, source_collection, regular_user):
        original_author = get_user_model().objects.create_user(
            email="author2@example.com", password="AuthorStrongPass123!"
        )
        source_collection.created_by = original_author
        source_collection.save()

        response = auth_client.post(
            reverse("sourcecollection-copy", args=[source_collection.pk]),
            {"new_collection_name": "Copy"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        copied = SourceCollection.objects.get(
            pk=response.json()["collection"]["collection_id"]
        )
        assert copied.created_by == regular_user
