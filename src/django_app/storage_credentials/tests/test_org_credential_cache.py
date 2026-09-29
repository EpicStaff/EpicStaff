"""Unit tests for OrgCredentialCache per-org locking.

Tests verify that concurrent `get()` calls for the same `org_id`:
1. Create exactly one StorageAdminGateway (not one per caller)
2. Don't leak old gateway sessions when rotating credentials
"""

import asyncio
import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from storage_credentials.services.org_credential_cache import (
    OrgCredentialCache,
)


@pytest.fixture
def mock_org_credentials():
    """Mock storage credentials."""
    credentials = MagicMock()
    credentials.access_key = "test-access-key"
    credentials.secret_key = "test-secret-key"
    return credentials


@pytest.fixture
def mock_gateway():
    """Mock StorageAdminGateway with async close method."""
    gateway = MagicMock()
    gateway.close = AsyncMock()
    return gateway


@pytest.fixture
def cache():
    """Fresh cache instance for each test."""
    return OrgCredentialCache()


@pytest.mark.asyncio
async def test_concurrent_get_same_org_creates_exactly_one_gateway(
    cache, mock_org_credentials, mock_gateway
):
    """Verify that two concurrent `get()` calls for the same org_id
    create exactly one StorageAdminGateway, not one per caller."""

    org_id = 42
    host = "https://minio.example.com"

    gateway_creation_count = 0

    def count_and_return_gateway(*args, **kwargs):
        nonlocal gateway_creation_count
        gateway_creation_count += 1
        return mock_gateway

    # Mock credentials fetch
    with patch(
        "storage_credentials.services.org_credential_cache._get_org_credentials",
        return_value=mock_org_credentials,
    ):
        # Mock StorageAdminGateway construction to track calls
        with patch(
            "storage_credentials.services.org_credential_cache.StorageAdminGateway",
            side_effect=count_and_return_gateway,
        ):
            # Launch two concurrent get() calls for the same org
            results = await asyncio.gather(
                cache.get(org_id=org_id, host=host),
                cache.get(org_id=org_id, host=host),
            )

    # Verify exactly one gateway was created
    assert gateway_creation_count == 1, (
        f"Expected exactly 1 gateway creation, got {gateway_creation_count}"
    )

    # Verify both callers got the same gateway instance
    assert results[0][1] is results[1][1], "Concurrent callers should get same gateway"


@pytest.mark.asyncio
async def test_concurrent_get_different_orgs_creates_separate_gateways(
    cache, mock_org_credentials
):
    """Verify that concurrent `get()` calls for different org_ids
    each create their own StorageAdminGateway (no over-locking)."""

    org_id_1 = 42
    org_id_2 = 99
    host = "https://minio.example.com"

    gateway_creation_count = 0
    gateways = []

    def count_and_return_unique_gateway(*args, **kwargs):
        nonlocal gateway_creation_count
        gateway_creation_count += 1
        gateway = MagicMock()
        gateway.close = AsyncMock()
        gateways.append(gateway)
        return gateway

    with patch(
        "storage_credentials.services.org_credential_cache._get_org_credentials",
        return_value=mock_org_credentials,
    ):
        with patch(
            "storage_credentials.services.org_credential_cache.StorageAdminGateway",
            side_effect=count_and_return_unique_gateway,
        ):
            results = await asyncio.gather(
                cache.get(org_id=org_id_1, host=host),
                cache.get(org_id=org_id_2, host=host),
            )

    # Verify two separate gateways were created (one per org)
    assert gateway_creation_count == 2, (
        f"Expected 2 gateways for different orgs, got {gateway_creation_count}"
    )

    # Verify they are different
    assert results[0][1] is not results[1][1], (
        "Different orgs should get different gateways"
    )


@pytest.mark.asyncio
async def test_expired_cache_entry_closes_old_gateway(
    cache, mock_org_credentials
):
    """Verify that when a cache entry expires and is refreshed,
    the old gateway's session is properly closed."""

    org_id = 42
    host = "https://minio.example.com"

    old_gateway = MagicMock()
    old_gateway.close = AsyncMock()

    new_gateway = MagicMock()
    new_gateway.close = AsyncMock()

    gateway_sequence = [old_gateway, new_gateway]
    gateway_index = 0

    def get_next_gateway(*args, **kwargs):
        nonlocal gateway_index
        gateway = gateway_sequence[gateway_index]
        gateway_index += 1
        return gateway

    with patch(
        "storage_credentials.services.org_credential_cache._get_org_credentials",
        return_value=mock_org_credentials,
    ):
        with patch(
            "storage_credentials.services.org_credential_cache.StorageAdminGateway",
            side_effect=get_next_gateway,
        ):
            # First call: populates cache with old_gateway
            credentials_1, gateway_1 = await cache.get(org_id=org_id, host=host)
            assert gateway_1 is old_gateway
            # Old gateway should not be closed yet (no previous entry)
            old_gateway.close.assert_not_called()

            # Manually expire the cache entry by modifying time
            entry = cache._entries[org_id]
            cache._entries[org_id] = dataclasses.replace(entry, cached_at=0)

            # Second call: should create new_gateway and close old_gateway
            credentials_2, gateway_2 = await cache.get(org_id=org_id, host=host)
            assert gateway_2 is new_gateway

            # Verify old gateway was closed during rotation
            old_gateway.close.assert_called_once()


@pytest.mark.asyncio
async def test_second_check_prevents_duplicate_creation(
    cache, mock_org_credentials
):
    """Verify double-checked locking: if two concurrent calls both
    miss the cache and both acquire locks, the second should see the
    entry created by the first and return it without creating another."""

    org_id = 42
    host = "https://minio.example.com"

    gateway_creation_count = 0
    creation_events = []

    def count_and_record_gateway(*args, **kwargs):
        nonlocal gateway_creation_count
        gateway_creation_count += 1
        creation_events.append("gateway_created")
        gateway = MagicMock()
        gateway.close = AsyncMock()
        return gateway

    with patch(
        "storage_credentials.services.org_credential_cache._get_org_credentials",
        return_value=mock_org_credentials,
    ):
        with patch(
            "storage_credentials.services.org_credential_cache.StorageAdminGateway",
            side_effect=count_and_record_gateway,
        ):
            # Two concurrent callers, both will acquire the lock in sequence
            results = await asyncio.gather(
                cache.get(org_id=org_id, host=host),
                cache.get(org_id=org_id, host=host),
            )

    # Only one gateway should be created
    assert gateway_creation_count == 1
    # Both should get the same gateway
    assert results[0][1] is results[1][1]


@pytest.mark.asyncio
async def test_no_session_leaks_on_concurrent_refresh(
    cache, mock_org_credentials
):
    """Verify no sessions are leaked when multiple concurrent calls
    trigger a cache refresh (expiry). Each old gateway should be closed
    exactly once."""

    org_id = 42
    host = "https://minio.example.com"

    # Pre-populate cache with initial gateway
    initial_gateway = MagicMock()
    initial_gateway.close = AsyncMock()

    with patch(
        "storage_credentials.services.org_credential_cache._get_org_credentials",
        return_value=mock_org_credentials,
    ):
        with patch(
            "storage_credentials.services.org_credential_cache.StorageAdminGateway",
            return_value=initial_gateway,
        ):
            await cache.get(org_id=org_id, host=host)

    # Expire the cache
    entry = cache._entries[org_id]
    cache._entries[org_id] = dataclasses.replace(entry, cached_at=0)

    # Track new gateways created
    new_gateways = []

    def create_new_gateway(*args, **kwargs):
        gateway = MagicMock()
        gateway.close = AsyncMock()
        new_gateways.append(gateway)
        return gateway

    with patch(
        "storage_credentials.services.org_credential_cache._get_org_credentials",
        return_value=mock_org_credentials,
    ):
        with patch(
            "storage_credentials.services.org_credential_cache.StorageAdminGateway",
            side_effect=create_new_gateway,
        ):
            # Three concurrent calls to refresh, all find cache expired
            results = await asyncio.gather(
                cache.get(org_id=org_id, host=host),
                cache.get(org_id=org_id, host=host),
                cache.get(org_id=org_id, host=host),
            )

    # Should create exactly one new gateway (not three)
    assert len(new_gateways) == 1
    # All callers should get the same new gateway
    assert results[0][1] is results[1][1] is results[2][1]

    # The old gateway should be closed exactly once (when refreshing)
    initial_gateway.close.assert_called_once()
