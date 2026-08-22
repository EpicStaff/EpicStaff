"""
Tests for SourceCollection description handling.

Covers the parts of the description feature that are unreachable through the
API test suite (auth baseline is broken there, see
tests/api_tests/knowledge_tests/test_collection_management.py):
- SourceCollectionCreateSerializer / SourceCollectionUpdateSerializer length
  validation on `description`
- CollectionManagementService.create_collection persisting `description`
- CollectionManagementService.copy_collection carrying the source
  `description` onto the copy
"""

import pytest

from tables.serializers.knowledge_serializers import (
    COLLECTION_DESCRIPTION_MAX_LENGTH,
    SourceCollectionCreateSerializer,
    SourceCollectionUpdateSerializer,
)
from tables.services.knowledge_services.collection_management_service import (
    CollectionManagementService,
)


class TestSourceCollectionCreateSerializerDescriptionValidation:
    def test_description_over_limit_rejected(self):
        serializer = SourceCollectionCreateSerializer(
            data={
                "collection_name": "Overlong Description Collection",
                "description": "x" * (COLLECTION_DESCRIPTION_MAX_LENGTH + 1),
            }
        )

        assert serializer.is_valid() is False
        assert "description" in serializer.errors

    def test_description_at_limit_accepted(self):
        serializer = SourceCollectionCreateSerializer(
            data={
                "collection_name": "At Limit Description Collection",
                "description": "x" * COLLECTION_DESCRIPTION_MAX_LENGTH,
            }
        )

        assert serializer.is_valid() is True


class TestSourceCollectionUpdateSerializerDescriptionValidation:
    def test_description_over_limit_rejected(self):
        serializer = SourceCollectionUpdateSerializer(
            data={
                "collection_name": "Existing Name",
                "description": "x" * (COLLECTION_DESCRIPTION_MAX_LENGTH + 1),
            }
        )

        assert serializer.is_valid() is False
        assert "description" in serializer.errors

    def test_description_at_limit_accepted(self):
        serializer = SourceCollectionUpdateSerializer(
            data={
                "collection_name": "Existing Name",
                "description": "x" * COLLECTION_DESCRIPTION_MAX_LENGTH,
            }
        )

        assert serializer.is_valid() is True


class TestCreateCollectionPersistsDescription:
    @pytest.mark.django_db
    def test_create_collection_persists_description(self, default_org):
        collection = CollectionManagementService.create_collection(
            collection_name="Documented Collection",
            description="Contains onboarding docs for new hires.",
            org_id=default_org.pk,
        )

        collection.refresh_from_db()
        assert collection.description == "Contains onboarding docs for new hires."


class TestCopyCollectionCarriesDescription:
    @pytest.mark.django_db
    def test_copy_collection_carries_source_description(self, default_org):
        source_collection = CollectionManagementService.create_collection(
            collection_name="Source Collection",
            description="Source description.",
            org_id=default_org.pk,
        )

        copied_collection = CollectionManagementService.copy_collection(
            source_collection_id=source_collection.collection_id,
            org_id=default_org.pk,
        )

        assert copied_collection.description == "Source description."

    @pytest.mark.django_db
    def test_copy_collection_with_blank_source_description_stays_blank(
        self, default_org
    ):
        source_collection = CollectionManagementService.create_collection(
            collection_name="Blank Description Source",
            org_id=default_org.pk,
        )

        copied_collection = CollectionManagementService.copy_collection(
            source_collection_id=source_collection.collection_id,
            org_id=default_org.pk,
        )

        assert copied_collection.description == ""
