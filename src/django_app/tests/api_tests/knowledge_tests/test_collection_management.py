"""
Tests for SourceCollection CRUD operations
"""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.knowledge_models import SourceCollection


@pytest.mark.django_db
class TestCollectionList:
    """Tests for listing collections."""

    def test_list_empty_collections(self, auth_client):
        """Test listing when no collections exist."""
        url = reverse("sourcecollection-list")
        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_list_collections(self, auth_client, source_collection, empty_collection):
        """Test listing existing collections."""
        url = reverse("sourcecollection-list")
        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 2
        assert all("collection_id" in item for item in data)
        assert all("collection_name" in item for item in data)
        assert all("description" in item for item in data)
        assert all("document_count" in item for item in data)


@pytest.mark.django_db
class TestCollectionCreate:
    """Tests for creating collections."""

    def test_create_collection_with_name(self, auth_client):
        """Test creating a collection with a specific name."""
        url = reverse("sourcecollection-list")
        data = {"collection_name": "My New Collection"}

        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        response_data = response.json()
        assert response_data["collection_name"] == "My New Collection"
        assert response_data["status"] == "empty"
        assert "collection_id" in response_data

        # Verify in database
        collection = SourceCollection.objects.get(
            collection_id=response_data["collection_id"]
        )
        assert collection.collection_name == "My New Collection"

    def test_create_collection_with_blank_name(self, auth_client):
        """Test creating a collection without specifying a name."""
        url = reverse("sourcecollection-list")
        data = {"collection_name": ""}

        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        response_data = response.json()
        assert "Untitled Collection" in response_data["collection_name"]

    def test_create_collection_with_description(self, auth_client):
        """Test creating a collection with a description."""
        url = reverse("sourcecollection-list")
        data = {
            "collection_name": "Documented Collection",
            "description": "Contains onboarding docs for new hires.",
        }

        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        response_data = response.json()
        assert response_data["description"] == "Contains onboarding docs for new hires."

        collection = SourceCollection.objects.get(
            collection_id=response_data["collection_id"]
        )
        assert collection.description == "Contains onboarding docs for new hires."

    def test_create_collection_with_too_long_description_rejected(self, auth_client):
        """Test creating a collection with a description over 2000 chars fails."""
        url = reverse("sourcecollection-list")
        data = {
            "collection_name": "Overlong Description Collection",
            "description": "x" * 2001,
        }

        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_duplicate_collection_name(self, auth_client, source_collection):
        """Test that duplicate collection names are handled correctly.

        The model has auto-rename logic, but the serializer validates uniqueness
        at the API level. This test verifies that creating with the same name
        multiple times results in auto-renamed collections via the model layer.
        """
        from tables.services.knowledge_services.collection_management_service import (
            CollectionManagementService,
        )

        test_collection_name = source_collection.collection_name
        collection_1 = CollectionManagementService.create_collection(
            collection_name=test_collection_name, user_id="test_user"
        )
        collection_2 = CollectionManagementService.create_collection(
            collection_name=test_collection_name, user_id="test_user"
        )

        # All should be created successfully with different names
        assert collection_1.collection_name != source_collection.collection_name
        assert collection_2.collection_name != collection_1.collection_name

        # Auto-renamed collections should have "(1)", "(2)", etc.
        all_names = [
            source_collection.collection_name,
            collection_1.collection_name,
            collection_2.collection_name,
        ]
        # At least some should have the rename pattern
        assert any("(" in name and ")" in name for name in all_names[1:])


@pytest.mark.django_db
class TestCollectionRetrieve:
    """Tests for retrieving a single collection."""

    def test_retrieve_collection(self, auth_client, source_collection):
        """Test retrieving a collection by ID."""
        url = reverse("sourcecollection-detail", args=[source_collection.collection_id])
        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["collection_id"] == source_collection.collection_id
        assert data["collection_name"] == source_collection.collection_name
        assert data["description"] == source_collection.description
        assert "document_count" in data

    def test_retrieve_nonexistent_collection(self, auth_client):
        """Test retrieving a collection that doesn't exist."""
        url = reverse("sourcecollection-detail", args=[99999])
        response = auth_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestCollectionUpdate:
    """Tests for updating collections."""

    def test_update_collection_name(self, auth_client, source_collection):
        """Test updating a collection's name."""
        url = reverse("sourcecollection-detail", args=[source_collection.collection_id])
        data = {"collection_name": "Updated Name"}

        response = auth_client.patch(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert response_data["collection_name"] == "Updated Name"

        # Verify in database
        source_collection.refresh_from_db()
        assert source_collection.collection_name == "Updated Name"

    def test_update_collection_description(self, auth_client, source_collection):
        """Test updating a collection's description."""
        url = reverse("sourcecollection-detail", args=[source_collection.collection_id])
        data = {"description": "Updated description."}

        response = auth_client.patch(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert response_data["description"] == "Updated description."

        source_collection.refresh_from_db()
        assert source_collection.description == "Updated description."

    def test_update_collection_with_too_long_description_rejected(
        self, auth_client, source_collection
    ):
        """Test updating with a description over 2000 chars fails validation."""
        url = reverse("sourcecollection-detail", args=[source_collection.collection_id])
        data = {"description": "x" * 2001}

        response = auth_client.patch(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_update_collection_with_empty_name(self, auth_client, source_collection):
        """Test updating with empty name fails validation."""
        url = reverse("sourcecollection-detail", args=[source_collection.collection_id])
        data = {"collection_name": ""}

        response = auth_client.patch(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_update_nonexistent_collection(self, auth_client):
        """Test updating a collection that doesn't exist."""
        url = reverse("sourcecollection-detail", args=[99999])
        data = {"collection_name": "New Name"}

        response = auth_client.patch(url, data, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestCollectionDelete:
    """Tests for deleting collections."""

    def test_delete_empty_collection(self, auth_client, empty_collection):
        """Test deleting an empty collection."""
        collection_id = empty_collection.collection_id
        url = reverse("sourcecollection-detail", args=[collection_id])

        response = auth_client.delete(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "message" in data
        assert data["deleted_documents"] == 0

        # Verify deletion
        assert not SourceCollection.objects.filter(collection_id=collection_id).exists()

    def test_delete_collection_with_documents(
        self, auth_client, source_collection, multiple_documents
    ):
        """Test deleting a collection with documents cascades properly."""
        collection_id = source_collection.collection_id
        document_ids = [doc.document_id for doc in multiple_documents]
        url = reverse("sourcecollection-detail", args=[collection_id])

        response = auth_client.delete(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["deleted_documents"] == 3

        # Verify cascade deletion
        from tables.models import DocumentMetadata

        for doc_id in document_ids:
            assert not DocumentMetadata.objects.filter(document_id=doc_id).exists()

    def test_delete_nonexistent_collection(self, auth_client):
        """Test deleting a collection that doesn't exist."""
        url = reverse("sourcecollection-detail", args=[99999])
        response = auth_client.delete(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestCollectionBulkDelete:
    """Tests for bulk deleting collections."""

    def test_bulk_delete_collections(
        self, auth_client, source_collection, empty_collection
    ):
        """Test bulk deleting multiple collections."""
        url = reverse("sourcecollection-bulk-delete")
        data = {
            "collection_ids": [
                source_collection.collection_id,
                empty_collection.collection_id,
            ]
        }

        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert response_data["deleted_count"] == 2

        # Verify deletion
        assert not SourceCollection.objects.filter(
            collection_id__in=[
                source_collection.collection_id,
                empty_collection.collection_id,
            ]
        ).exists()

    def test_bulk_delete_with_empty_list(self, auth_client):
        """Test bulk delete with empty collection_ids list."""
        url = reverse("sourcecollection-bulk-delete")
        data = {"collection_ids": []}

        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_bulk_delete_with_missing_ids(self, auth_client, source_collection):
        """Test bulk delete with some nonexistent IDs."""
        url = reverse("sourcecollection-bulk-delete")
        data = {"collection_ids": [source_collection.collection_id, 99999]}

        response = auth_client.post(url, data, format="json")

        # Should delete the existing one and ignore the missing one
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert response_data["deleted_count"] >= 1


@pytest.mark.django_db
class TestCollectionCopy:
    """Tests for copying collections."""

    def test_copy_collection(self, auth_client, source_collection, multiple_documents):
        """Test copying a collection creates new metadata but shares content."""
        url = reverse("sourcecollection-copy", args=[source_collection.collection_id])
        data = {"new_collection_name": "Copied Collection"}

        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        response_data = response.json()
        assert response_data["collection"]["collection_name"] == "Copied Collection"

        new_collection_id = response_data["collection"]["collection_id"]

        # Verify new collection has same document count
        from tables.models import DocumentMetadata

        original_count = DocumentMetadata.objects.filter(
            source_collection=source_collection
        ).count()
        copied_count = DocumentMetadata.objects.filter(
            source_collection_id=new_collection_id
        ).count()
        assert original_count == copied_count

    def test_copy_collection_carries_description(self, auth_client, source_collection):
        """Test copying a collection carries the source description to the copy."""
        source_collection.description = "Source description."
        source_collection.save()

        url = reverse("sourcecollection-copy", args=[source_collection.collection_id])
        response = auth_client.post(url, {}, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        response_data = response.json()
        assert response_data["collection"]["description"] == "Source description."

    def test_copy_collection_without_name(self, auth_client, source_collection):
        """Test copying without providing a new name."""
        url = reverse("sourcecollection-copy", args=[source_collection.collection_id])
        data = {}

        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        response_data = response.json()
        # Should auto-generate name with "(Copy)" suffix
        assert "(Copy)" in response_data["collection"]["collection_name"]

    def test_copy_nonexistent_collection(self, auth_client):
        """Test copying a collection that doesn't exist."""
        url = reverse("sourcecollection-copy", args=[99999])
        data = {}

        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
