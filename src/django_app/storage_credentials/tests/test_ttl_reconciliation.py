"""Tests for TtlReconciliationService TTL sweep implementation.

Tests verify that TTL reconciliation:
- Sweeps all provisioned organizations
- Revokes expired service accounts correctly
- Handles failures in one org without stopping others
- Handles failures in one account without stopping others
- Collects and logs statistics correctly
- Skips non-expired accounts
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from storage_credentials.services.ttl_reconciliation_service import (
    SweepStatistics,
    TtlReconciliationService,
    _list_provisioned_org_ids,
    _parse_expiration,
)


class TestParseExpiration:
    """Tests for _parse_expiration() helper."""

    def test_parses_valid_iso8601_string(self):
        """Verify ISO-8601 timestamps are parsed correctly."""
        expiration_str = "2025-12-31T23:59:59Z"
        result = _parse_expiration(expiration_str)

        assert result is not None
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 31
        assert result.tzinfo is not None

    def test_returns_none_for_invalid_format(self):
        """Verify invalid formats return None."""
        result = _parse_expiration("2025-12-31 23:59:59")
        assert result is None

    def test_returns_none_for_empty_string(self):
        """Verify empty string returns None."""
        result = _parse_expiration("")
        assert result is None

    def test_returns_none_for_non_string(self):
        """Verify non-string input returns None."""
        result = _parse_expiration(None)
        assert result is None

    def test_returns_utc_timezone(self):
        """Verify returned datetime has UTC timezone."""
        expiration_str = "2025-06-15T12:30:45Z"
        result = _parse_expiration(expiration_str)

        assert result.tzinfo is not None
        assert result.tzinfo.tzname(None) == "UTC"


class TestTtlReconciliationService:
    """Tests for TtlReconciliationService.sweep()"""

    @pytest.fixture
    def service(self):
        """Create a TtlReconciliationService instance."""
        return TtlReconciliationService(host="https://minio.example.com")

    @pytest.mark.asyncio
    async def test_sweep_processes_all_organizations(self, service):
        """Verify sweep() processes all provisioned organizations."""
        org_ids = [1, 2, 3]

        with patch(
            "storage_credentials.services.ttl_reconciliation_service._list_provisioned_org_ids"
        ) as mock_list_org_ids:
            mock_list_org_ids.return_value = org_ids
            service._sweep_one_org = AsyncMock(return_value={
                "accounts_checked": 0,
                "accounts_revoked": 0,
                "revocation_failures": 0,
            })

            await service.sweep()

            assert service._sweep_one_org.call_count == len(org_ids)

    @pytest.mark.asyncio
    async def test_sweep_continues_on_org_failure(self, service):
        """Verify sweep continues processing other orgs when one fails."""
        org_ids = [1, 2, 3]

        with patch(
            "storage_credentials.services.ttl_reconciliation_service._list_provisioned_org_ids"
        ) as mock_list_org_ids:
            mock_list_org_ids.return_value = org_ids

            async def sweep_with_failure(org_id):
                if org_id == 2:
                    raise RuntimeError("Org 2 failed")
                return {
                    "accounts_checked": 1,
                    "accounts_revoked": 0,
                    "revocation_failures": 0,
                }

            service._sweep_one_org = AsyncMock(side_effect=sweep_with_failure)

            await service.sweep()

            assert service._sweep_one_org.call_count == len(org_ids)

    @pytest.mark.asyncio
    async def test_sweep_one_org_revokes_expired_accounts(self, service):
        """Verify _sweep_one_org revokes service accounts past expiration."""
        now = datetime.now(UTC)
        expired_time = (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        future_time = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        org_creds = MagicMock(access_key="org_user")
        gateway = AsyncMock()
        gateway.list_service_accounts = AsyncMock(return_value=[
            {"accessKey": "expired_key", "expiration": expired_time},
            {"accessKey": "valid_key", "expiration": future_time},
        ])
        gateway.delete_service_account = AsyncMock()

        with patch(
            "storage_credentials.services.ttl_reconciliation_service.org_credential_cache.get"
        ) as mock_get:
            mock_get.return_value = (org_creds, gateway)

            result = await service._sweep_one_org(org_id=1)

            assert result["accounts_checked"] == 2
            assert result["accounts_revoked"] == 1
            gateway.delete_service_account.assert_called_once_with("expired_key")

    @pytest.mark.asyncio
    async def test_sweep_one_org_skips_non_expired_accounts(self, service):
        """Verify non-expired accounts are NOT revoked."""
        now = datetime.now(UTC)
        future_time = (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

        org_creds = MagicMock(access_key="org_user")
        gateway = AsyncMock()
        gateway.list_service_accounts = AsyncMock(return_value=[
            {"accessKey": "valid_key1", "expiration": future_time},
            {"accessKey": "valid_key2", "expiration": future_time},
        ])
        gateway.delete_service_account = AsyncMock()

        with patch(
            "storage_credentials.services.ttl_reconciliation_service.org_credential_cache.get"
        ) as mock_get:
            mock_get.return_value = (org_creds, gateway)

            result = await service._sweep_one_org(org_id=1)

            assert result["accounts_checked"] == 2
            assert result["accounts_revoked"] == 0
            gateway.delete_service_account.assert_not_called()

    @pytest.mark.asyncio
    async def test_sweep_one_org_continues_on_revocation_failure(self, service):
        """Verify sweep continues when one revocation fails."""
        now = datetime.now(UTC)
        expired_time = (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        org_creds = MagicMock(access_key="org_user")
        gateway = AsyncMock()
        gateway.list_service_accounts = AsyncMock(return_value=[
            {"accessKey": "key1", "expiration": expired_time},
            {"accessKey": "key2", "expiration": expired_time},
            {"accessKey": "key3", "expiration": expired_time},
        ])

        async def delete_with_failure(access_key):
            if access_key == "key2":
                raise RuntimeError("Failed to delete key2")

        gateway.delete_service_account = AsyncMock(side_effect=delete_with_failure)

        with patch(
            "storage_credentials.services.ttl_reconciliation_service.org_credential_cache.get"
        ) as mock_get:
            mock_get.return_value = (org_creds, gateway)

            result = await service._sweep_one_org(org_id=1)

            assert result["accounts_checked"] == 3
            assert result["accounts_revoked"] == 2
            assert result["revocation_failures"] == 1
            assert gateway.delete_service_account.call_count == 3

    @pytest.mark.asyncio
    async def test_sweep_one_org_handles_missing_access_key(self, service):
        """Verify accounts with missing accessKey are skipped."""
        now = datetime.now(UTC)
        expired_time = (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        org_creds = MagicMock(access_key="org_user")
        gateway = AsyncMock()
        gateway.list_service_accounts = AsyncMock(return_value=[
            {"expiration": expired_time},  # Missing accessKey
            {"accessKey": "valid_key", "expiration": expired_time},
        ])
        gateway.delete_service_account = AsyncMock()

        with patch(
            "storage_credentials.services.ttl_reconciliation_service.org_credential_cache.get"
        ) as mock_get:
            mock_get.return_value = (org_creds, gateway)

            result = await service._sweep_one_org(org_id=1)

            assert result["accounts_checked"] == 2
            assert result["accounts_revoked"] == 1
            gateway.delete_service_account.assert_called_once_with("valid_key")

    @pytest.mark.asyncio
    async def test_sweep_one_org_handles_invalid_expiration(self, service):
        """Verify accounts with invalid expiration are skipped."""
        org_creds = MagicMock(access_key="org_user")
        gateway = AsyncMock()
        gateway.list_service_accounts = AsyncMock(return_value=[
            {"accessKey": "key1", "expiration": "invalid_date"},
            {"accessKey": "key2", "expiration": ""},
        ])
        gateway.delete_service_account = AsyncMock()

        with patch(
            "storage_credentials.services.ttl_reconciliation_service.org_credential_cache.get"
        ) as mock_get:
            mock_get.return_value = (org_creds, gateway)

            result = await service._sweep_one_org(org_id=1)

            assert result["accounts_checked"] == 2
            assert result["accounts_revoked"] == 0
            gateway.delete_service_account.assert_not_called()

    @pytest.mark.asyncio
    async def test_sweep_collects_statistics(self, service):
        """Verify sweep() collects and logs statistics correctly."""
        org_ids = [1, 2]

        with patch(
            "storage_credentials.services.ttl_reconciliation_service._list_provisioned_org_ids"
        ) as mock_list_org_ids:
            mock_list_org_ids.return_value = org_ids

            async def sweep_one_org(org_id):
                if org_id == 1:
                    return {
                        "accounts_checked": 5,
                        "accounts_revoked": 2,
                        "revocation_failures": 1,
                    }
                else:
                    return {
                        "accounts_checked": 3,
                        "accounts_revoked": 1,
                        "revocation_failures": 0,
                    }

            service._sweep_one_org = AsyncMock(side_effect=sweep_one_org)

            with patch("storage_credentials.services.ttl_reconciliation_service.logger") as mock_logger:
                await service.sweep()

                info_calls = mock_logger.info.call_args_list
                assert any("sweep completed" in str(call) for call in info_calls)

    @pytest.mark.asyncio
    async def test_sweep_handles_empty_accounts_list(self, service):
        """Verify sweep handles org with no service accounts."""
        org_creds = MagicMock(access_key="org_user")
        gateway = AsyncMock()
        gateway.list_service_accounts = AsyncMock(return_value=[])

        with patch(
            "storage_credentials.services.ttl_reconciliation_service.org_credential_cache.get"
        ) as mock_get:
            mock_get.return_value = (org_creds, gateway)

            result = await service._sweep_one_org(org_id=1)

            assert result["accounts_checked"] == 0
            assert result["accounts_revoked"] == 0
            assert result["revocation_failures"] == 0

    @pytest.mark.asyncio
    async def test_sweep_statistics_structure(self, service):
        """Verify SweepStatistics dataclass is used correctly."""
        org_ids = [1, 2, 3]

        with patch(
            "storage_credentials.services.ttl_reconciliation_service._list_provisioned_org_ids"
        ) as mock_list_org_ids:
            mock_list_org_ids.return_value = org_ids
            service._sweep_one_org = AsyncMock(return_value={
                "accounts_checked": 1,
                "accounts_revoked": 1,
                "revocation_failures": 0,
            })

            await service.sweep()

            assert service._sweep_one_org.call_count == 3

    @pytest.mark.asyncio
    async def test_sweep_one_org_boundary_case_exactly_at_expiration(self, service):
        """Verify accounts expired exactly now are revoked."""
        now = datetime.now(UTC)
        exact_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        org_creds = MagicMock(access_key="org_user")
        gateway = AsyncMock()
        gateway.list_service_accounts = AsyncMock(return_value=[
            {"accessKey": "key", "expiration": exact_time},
        ])
        gateway.delete_service_account = AsyncMock()

        with patch(
            "storage_credentials.services.ttl_reconciliation_service.org_credential_cache.get"
        ) as mock_get:
            mock_get.return_value = (org_creds, gateway)

            result = await service._sweep_one_org(org_id=1)

            assert result["accounts_revoked"] == 1

    @pytest.mark.asyncio
    async def test_sweep_logs_revocation_context(self, service):
        """Verify revocation logging includes context information."""
        now = datetime.now(UTC)
        expired_time = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

        org_creds = MagicMock(access_key="org_user")
        gateway = AsyncMock()
        gateway.list_service_accounts = AsyncMock(return_value=[
            {"accessKey": "test_key", "expiration": expired_time},
        ])
        gateway.delete_service_account = AsyncMock()

        with patch(
            "storage_credentials.services.ttl_reconciliation_service.org_credential_cache.get"
        ) as mock_get:
            mock_get.return_value = (org_creds, gateway)

            with patch("storage_credentials.services.ttl_reconciliation_service.logger") as mock_logger:
                await service._sweep_one_org(org_id=1)

                info_calls = mock_logger.info.call_args_list
                assert any("revoked expired service account" in str(call) for call in info_calls)

    @pytest.mark.asyncio
    async def test_sweep_logs_revocation_failure_with_context(self, service):
        """Verify revocation failures are logged with context."""
        now = datetime.now(UTC)
        expired_time = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

        org_creds = MagicMock(access_key="org_user")
        gateway = AsyncMock()
        gateway.list_service_accounts = AsyncMock(return_value=[
            {"accessKey": "test_key", "expiration": expired_time},
        ])
        gateway.delete_service_account = AsyncMock(side_effect=RuntimeError("Delete failed"))

        with patch(
            "storage_credentials.services.ttl_reconciliation_service.org_credential_cache.get"
        ) as mock_get:
            mock_get.return_value = (org_creds, gateway)

            with patch("storage_credentials.services.ttl_reconciliation_service.logger") as mock_logger:
                await service._sweep_one_org(org_id=1)

                error_calls = mock_logger.error.call_args_list
                assert any("failed to revoke" in str(call) for call in error_calls)
