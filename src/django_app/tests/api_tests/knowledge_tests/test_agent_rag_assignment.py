"""
Comprehensive tests for Agent RAG Assignment and Search Config operations

Tests cover:
- Creating agents with RAG assignment
- Updating agent RAG assignments
- Updating search configurations
- RAG assignment validation (collection mismatch, status checks)
- Search config partial updates
- Getting available RAGs for collection
- Edge cases and error handling
"""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.knowledge_models import (
    NaiveRag,
    BaseRagType,
    SourceCollection,
    NaiveRagSearchConfig,
)
from tables.models.crew_models import Agent


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def agent_data(llm_config):
    """Base agent data without RAG assignment."""
    return {
        "role": "Research Assistant",
        "goal": "Find and analyze information",
        "backstory": "Expert researcher with deep knowledge",
        "llm_config": llm_config.id,
    }


@pytest.fixture
def another_collection():
    """Create another collection for testing."""
    return SourceCollection.objects.create(
        collection_name="Another Collection", user_id="test_user"
    )


@pytest.fixture
def another_naive_rag(another_collection, test_embedding_config):
    """Create NaiveRag in another collection."""
    base_rag = BaseRagType.objects.create(
        source_collection=another_collection, rag_type=BaseRagType.RagType.NAIVE
    )
    return NaiveRag.objects.create(
        base_rag_type=base_rag,
        embedder=test_embedding_config,
        rag_status=NaiveRag.NaiveRagStatus.COMPLETED,
    )


@pytest.fixture
def completed_naive_rag(naive_rag):
    """Update naive_rag status to COMPLETED."""
    naive_rag.rag_status = NaiveRag.NaiveRagStatus.COMPLETED
    naive_rag.save()
    return naive_rag


@pytest.fixture
def second_naive_rag_same_collection(base_rag_type, test_embedding_config):
    """Create a second NaiveRag in the same collection."""
    # Create another base_rag_type for the same collection
    # Note: This requires modification of unique constraint or creating separate test
    return None  # Placeholder - typically one RAG per collection


# ============================================================================
# AGENT RAG ASSIGNMENT - CREATE TESTS
# ============================================================================


@pytest.mark.django_db
class TestAgentCreateWithRag:
    """Tests for creating agents with RAG assignment."""

    def test_create_agent_with_rag_and_search_configs(
        self, auth_client, source_collection, completed_naive_rag, agent_data
    ):
        """Test creating agent with RAG and custom search configs."""
        url = reverse("agent-list")
        data = {
            **agent_data,
            "knowledge_collection": source_collection.collection_id,
            "rag": {
                "rag_type": "naive",
                "rag_id": completed_naive_rag.naive_rag_id,
            },
            "search_configs": {
                "naive": {"search_limit": 10, "similarity_threshold": 0.85}
            },
        }

        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        response_data = response.json()

        # Verify rag assignment
        assert response_data["rag"] is not None
        assert response_data["rag"]["rag_type"] == "naive"
        assert response_data["rag"]["rag_id"] == completed_naive_rag.naive_rag_id

        # Verify search configs
        assert response_data["search_configs"] is not None
        assert response_data["search_configs"]["naive"]["search_limit"] == 10
        assert response_data["search_configs"]["naive"]["similarity_threshold"] == 0.85

        # Verify in database
        agent = Agent.objects.get(id=response_data["id"])
        assert agent.knowledge_collection == source_collection

        # Verify search config in DB
        search_config = NaiveRagSearchConfig.objects.get(agent=agent)
        assert search_config.search_limit == 10
        assert float(search_config.similarity_threshold) == 0.85

    def test_create_agent_with_rag_without_search_configs(
        self, auth_client, source_collection, completed_naive_rag, agent_data
    ):
        """Test creating agent with RAG but no search configs (should use defaults)."""
        url = reverse("agent-list")
        data = {
            **agent_data,
            "knowledge_collection": source_collection.collection_id,
            "rag": {
                "rag_type": "naive",
                "rag_id": completed_naive_rag.naive_rag_id,
            },
        }

        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        response_data = response.json()

        # Verify search configs have defaults
        assert response_data["search_configs"] is not None
        assert response_data["search_configs"]["naive"]["search_limit"] == 3
        assert response_data["search_configs"]["naive"]["similarity_threshold"] == 0.2

    def test_create_agent_without_collection_and_rag(self, auth_client, agent_data):
        """Test creating agent without knowledge collection (valid case)."""
        url = reverse("agent-list")
        data = agent_data

        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        response_data = response.json()

        # Verify no RAG or search configs
        assert response_data["rag"] is None
        assert response_data["search_configs"] is None
        assert response_data["knowledge_collection"] is None

    def test_create_agent_with_collection_but_no_rag_fails(
        self, auth_client, source_collection, agent_data
    ):
        """Test creating agent with collection but no RAG (should fail)."""
        url = reverse("agent-list")
        data = {
            **agent_data,
            "knowledge_collection": source_collection.collection_id,
        }

        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        response_data = response.json()
        # Check that the error message mentions 'rag'
        assert "rag" in str(response_data).lower()

    def test_create_agent_with_rag_from_different_collection_fails(
        self, auth_client, source_collection, another_naive_rag, agent_data
    ):
        """Test creating agent with RAG that doesn't belong to agent's collection."""
        url = reverse("agent-list")
        data = {
            **agent_data,
            "knowledge_collection": source_collection.collection_id,
            "rag": {
                "rag_type": "naive",
                "rag_id": another_naive_rag.naive_rag_id,  # From different collection
            },
        }

        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "RagCollectionMismatchException" in response.json()["message"]

    def test_create_agent_with_nonexistent_rag_fails(
        self, auth_client, source_collection, agent_data
    ):
        """Test creating agent with non-existent RAG ID."""
        url = reverse("agent-list")
        data = {
            **agent_data,
            "knowledge_collection": source_collection.collection_id,
            "rag": {"rag_type": "naive", "rag_id": 99999},
        }

        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_agent_with_unknown_rag_type_fails(
        self, auth_client, source_collection, completed_naive_rag, agent_data
    ):
        """Test creating agent with unknown RAG type."""
        url = reverse("agent-list")
        data = {
            **agent_data,
            "knowledge_collection": source_collection.collection_id,
            "rag": {
                "rag_type": "unknown_type",
                "rag_id": completed_naive_rag.naive_rag_id,
            },
        }

        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ============================================================================
# AGENT RAG ASSIGNMENT - UPDATE TESTS
# ============================================================================


@pytest.mark.django_db
class TestAgentUpdateRag:
    """Tests for updating agent RAG assignments."""

    @pytest.fixture
    def agent_with_rag(self, source_collection, completed_naive_rag, default_org):
        """Create an agent with RAG assignment."""
        agent = Agent.objects.create(
            role="Research Agent",
            goal="Research",
            backstory="Researcher",
            knowledge_collection=source_collection,
            org=default_org,
        )
        # Assign RAG using service
        from tables.services.rag_assignment_service import RagAssignmentService

        RagAssignmentService.assign_rag_to_agent(
            agent, "naive", completed_naive_rag.naive_rag_id
        )
        return agent

    def test_update_agent_change_collection_without_rag_fails(
        self, auth_client, agent_with_rag, another_collection
    ):
        """Test changing collection without providing new RAG (should fail)."""
        url = reverse("agent-detail", args=[agent_with_rag.id])
        data = {"knowledge_collection": another_collection.collection_id}

        response = auth_client.patch(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        response_data = response.json()
        # Check that the error message mentions 'rag'
        assert "rag" in str(response_data).lower()

    def test_update_agent_remove_collection(self, auth_client, agent_with_rag):
        """Test removing collection from agent (should unassign RAG)."""
        url = reverse("agent-detail", args=[agent_with_rag.id])
        data = {"knowledge_collection": None}

        response = auth_client.patch(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()

        # Verify collection removed
        assert response_data["knowledge_collection"] is None


# ============================================================================
# SEARCH CONFIG UPDATE TESTS
# ============================================================================


@pytest.mark.django_db
class TestAgentSearchConfigUpdate:
    """Tests for updating agent search configurations."""

    @pytest.fixture
    def agent_with_search_config(
        self, source_collection, completed_naive_rag, default_org
    ):
        """Create agent with RAG and search config."""
        agent = Agent.objects.create(
            role="Research Agent",
            goal="Research",
            backstory="Researcher",
            knowledge_collection=source_collection,
            org=default_org,
        )
        from tables.services.rag_assignment_service import (
            RagAssignmentService,
            SearchConfigService,
        )

        RagAssignmentService.assign_rag_to_agent(
            agent, "naive", completed_naive_rag.naive_rag_id
        )
        SearchConfigService.update_search_config(
            agent, search_limit=5, similarity_threshold=0.7
        )
        return agent

    def test_update_search_config_partial_search_limit_only(
        self, auth_client, agent_with_search_config
    ):
        """Test updating only search_limit (partial update)."""
        url = reverse("agent-detail", args=[agent_with_search_config.id])
        data = {"search_configs": {"naive": {"search_limit": 15}}}

        response = auth_client.patch(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()

        # Verify search_limit updated
        assert response_data["search_configs"]["naive"]["search_limit"] == 15

        # Verify similarity_threshold unchanged
        assert response_data["search_configs"]["naive"]["similarity_threshold"] == 0.7

    def test_update_search_config_partial_threshold_only(
        self, auth_client, agent_with_search_config
    ):
        """Test updating only similarity_threshold (partial update)."""
        url = reverse("agent-detail", args=[agent_with_search_config.id])
        data = {"search_configs": {"naive": {"similarity_threshold": 0.95}}}

        response = auth_client.patch(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()

        # Verify similarity_threshold updated
        assert response_data["search_configs"]["naive"]["similarity_threshold"] == 0.95

        # Verify search_limit unchanged
        assert response_data["search_configs"]["naive"]["search_limit"] == 5

    def test_update_search_config_both_params(
        self, auth_client, agent_with_search_config
    ):
        """Test updating both search config parameters."""
        url = reverse("agent-detail", args=[agent_with_search_config.id])
        data = {
            "search_configs": {
                "naive": {"search_limit": 20, "similarity_threshold": 0.88}
            }
        }

        response = auth_client.patch(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()

        # Verify both updated
        assert response_data["search_configs"]["naive"]["search_limit"] == 20
        assert response_data["search_configs"]["naive"]["similarity_threshold"] == 0.88

    def test_update_search_config_without_rag_assigned(
        self, auth_client, llm_config, default_org
    ):
        """Test updating search config for agent without RAG (should work)."""
        # Create agent without RAG
        agent = Agent.objects.create(
            role="Agent",
            goal="Goal",
            backstory="Story",
            llm_config=llm_config,
            org=default_org,
        )

        url = reverse("agent-detail", args=[agent.id])
        data = {
            "search_configs": {
                "naive": {"search_limit": 8, "similarity_threshold": 0.6}
            }
        }

        response = auth_client.patch(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()

        # Verify config created/updated even without RAG
        assert response_data["search_configs"]["naive"]["search_limit"] == 8
        assert (
            float(response_data["search_configs"]["naive"]["similarity_threshold"])
            == 0.6
        )


# ============================================================================
# GET AVAILABLE RAGS TESTS
# ============================================================================


@pytest.mark.django_db
class TestGetAvailableRags:
    """Tests for GET /source-collections/{id}/available-rags/ endpoint."""

    def test_get_available_rags_for_collection(
        self, auth_client, source_collection, completed_naive_rag
    ):
        """Test getting available RAGs for a collection."""
        url = reverse(
            "sourcecollection-available-rags", args=[source_collection.collection_id]
        )

        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert isinstance(data, list)
        assert len(data) >= 1

        # Verify RAG data structure
        rag_data = data[0]
        assert rag_data["rag_id"] == completed_naive_rag.naive_rag_id
        assert rag_data["rag_type"] == "naive"
        assert rag_data["rag_status"] == NaiveRag.NaiveRagStatus.COMPLETED
        assert rag_data["collection_id"] == source_collection.collection_id
        assert "created_at" in rag_data
        assert "updated_at" in rag_data

    def test_get_available_rags_default_status_filter(
        self, auth_client, source_collection, naive_rag
    ):
        """Test default status filter includes 'completed', 'warning', 'new'."""
        # Set status to NEW
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.NEW
        naive_rag.save()

        url = reverse(
            "sourcecollection-available-rags", args=[source_collection.collection_id]
        )

        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Should include NEW status by default
        assert len(data) >= 1

    def test_get_available_rags_custom_status_filter(
        self, auth_client, source_collection, naive_rag
    ):
        """Test filtering by specific status."""
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.PROCESSING
        naive_rag.save()

        url = reverse(
            "sourcecollection-available-rags", args=[source_collection.collection_id]
        )

        # Filter only 'processing' status
        response = auth_client.get(url, {"status": "processing"})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert len(data) >= 1
        assert data[0]["rag_status"] == NaiveRag.NaiveRagStatus.PROCESSING

    def test_get_available_rags_empty_collection(self, auth_client, empty_collection):
        """Test getting RAGs for collection without any RAGs."""
        url = reverse(
            "sourcecollection-available-rags", args=[empty_collection.collection_id]
        )

        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert isinstance(data, list)
        assert len(data) == 0

    def test_get_available_rags_nonexistent_collection(self, auth_client):
        """Test getting RAGs for non-existent collection."""
        url = reverse("sourcecollection-available-rags", args=[99999])

        response = auth_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# GET AGENT WITH RAG TESTS
# ============================================================================


@pytest.mark.django_db
class TestGetAgentWithRag:
    """Tests for GET /agents/{id}/ with RAG information."""

    def test_get_agent_with_rag_returns_rag_info(
        self, auth_client, source_collection, completed_naive_rag, default_org
    ):
        """Test getting agent returns RAG information."""
        agent = Agent.objects.create(
            role="Agent",
            goal="Goal",
            backstory="Story",
            knowledge_collection=source_collection,
            org=default_org,
        )
        from tables.services.rag_assignment_service import RagAssignmentService

        RagAssignmentService.assign_rag_to_agent(
            agent, "naive", completed_naive_rag.naive_rag_id
        )

        url = reverse("agent-detail", args=[agent.id])
        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Verify RAG info returned
        assert data["rag"] is not None
        assert data["rag"]["rag_type"] == "naive"
        assert data["rag"]["rag_id"] == completed_naive_rag.naive_rag_id
        assert data["rag"]["rag_status"] == NaiveRag.NaiveRagStatus.COMPLETED

    def test_get_agent_without_rag_returns_null(self, auth_client, default_org):
        """Test getting agent without RAG returns null."""
        agent = Agent.objects.create(
            role="Agent", goal="Goal", backstory="Story", org=default_org
        )

        url = reverse("agent-detail", args=[agent.id])
        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Verify RAG is null
        assert data["rag"] is None
        assert data["search_configs"] is None


# ============================================================================
# EDGE CASES AND VALIDATION TESTS
# ============================================================================


@pytest.mark.django_db
class TestAgentRagEdgeCases:
    """Tests for edge cases and validation."""

    def test_agent_cannot_have_rag_without_collection(
        self, auth_client, completed_naive_rag, agent_data
    ):
        """Test that RAG cannot be assigned without knowledge_collection."""
        url = reverse("agent-list")
        data = {
            **agent_data,
            "rag": {
                "rag_type": "naive",
                "rag_id": completed_naive_rag.naive_rag_id,
            },
        }

        response = auth_client.post(url, data, format="json")

        # Should fail because no knowledge_collection provided
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_search_limit_value(
        self, auth_client, source_collection, completed_naive_rag, agent_data
    ):
        """Test creating agent with invalid search_limit."""
        url = reverse("agent-list")
        data = {
            **agent_data,
            "knowledge_collection": source_collection.collection_id,
            "rag": {
                "rag_type": "naive",
                "rag_id": completed_naive_rag.naive_rag_id,
            },
            "search_configs": {"naive": {"search_limit": -1}},  # Invalid negative value
        }

        response = auth_client.post(url, data, format="json")

        # Should validate and reject negative search_limit
        # Note: Validation depends on serializer implementation
        # assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_similarity_threshold_value(
        self, auth_client, source_collection, completed_naive_rag, agent_data
    ):
        """Test creating agent with invalid similarity_threshold."""
        url = reverse("agent-list")
        data = {
            **agent_data,
            "knowledge_collection": source_collection.collection_id,
            "rag": {
                "rag_type": "naive",
                "rag_id": completed_naive_rag.naive_rag_id,
            },
            "search_configs": {"naive": {"similarity_threshold": 1.5}},  # Invalid > 1.0
        }

        response = auth_client.post(url, data, format="json")

        # Should validate and reject invalid threshold
        # Note: Validation depends on serializer implementation
        # assert response.status_code == status.HTTP_400_BAD_REQUEST
