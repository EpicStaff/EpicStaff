"""Live-fire test of the Deny statement blocking self-minting.

This is a SECURITY-CRITICAL integration test that verifies a temporary
credential cannot self-mint a sibling service account, and that the Deny
statement's `Resource: ["arn:aws:s3:::*"]` is what actually blocks it
against a real RustFS backend (not just plausible by analogy with MinIO).

Excluded from the default test run (registered as `integration` in
pyproject.toml, deselected by default `addopts`). To run:

    docker compose --env-file=.dev.env up -d storage django_app storage-credential-issuer webhook
    pytest src/django_app/storage_credentials/tests/test_live_deny_self_mint.py -m integration -v

Requires the real `storage` (RustFS) docker service reachable at
STORAGE_HOST, and a real Postgres connection (uses `transactional_db`,
not `db`: credential issuance goes through `asyncio.to_thread()` on a
fresh DB connection, which cannot see a row written inside a
non-committing transaction -- it needs the row actually committed).
"""

import asyncio
import os
from dataclasses import dataclass
from datetime import timedelta

import pytest
from rbac.models import Organization

from storage_credentials.clients.minio_admin_client import StorageAdminGateway
from storage_credentials.exceptions import TemporaryCredentialIssueError
from storage_credentials.policies import build_org_user_policy, build_temporary_policy
from storage_credentials.services.org_credential_store import org_credential_store
from storage_credentials.services.temporary_credential_service import (
    TemporaryCredentialService,
)


@dataclass
class LiveTestConfig:
    """Configuration for the live test."""

    storage_host: str = os.getenv("STORAGE_HOST", "http://storage:9000")
    bucket: str = os.getenv("STORAGE_BUCKET", "epicstaff")


@pytest.mark.integration
class TestLiveDenySelfMint:
    """Live-fire test of Deny statement blocking self-minting."""

    @pytest.fixture
    def config(self):
        return LiveTestConfig()

    @pytest.fixture
    def test_org(self, transactional_db):
        return Organization.objects.create(name="Test Security Org")

    @pytest.fixture
    def org_with_provisioned_credentials(self, transactional_db, test_org, config):
        """Provision org-level storage credentials via the gateway.

        Simulates the initial provisioning step where an admin has granted
        the org a set of long-lived storage IAM credentials.
        """
        org_prefix = f"org_{test_org.id}"
        policy = build_org_user_policy(config.bucket, org_prefix)

        async def provision():
            gateway = StorageAdminGateway(
                host=config.storage_host, access_key="minioadmin", secret_key="minioadmin"
            )
            try:
                return await gateway.create_service_account(
                    policy=policy, expiration=timedelta(days=365)
                )
            finally:
                await gateway.close()

        try:
            access_key, secret_key = asyncio.run(provision())
        except TemporaryCredentialIssueError as e:
            pytest.skip(f"Storage service not available at {config.storage_host}: {e}")

        org_credential_store.save(org=test_org, access_key=access_key, secret_key=secret_key)
        return test_org

    @pytest.mark.asyncio
    async def test_temporary_credential_cannot_self_mint(
        self, config, org_with_provisioned_credentials
    ):
        """A temporary credential's Deny statement (Resource: ["arn:aws:s3:::*"])
        must block it from minting a sibling service account -- the anti-TTL-
        escape guard this whole test exists to prove still holds on RustFS."""
        test_org = org_with_provisioned_credentials
        org_prefix = f"org_{test_org.id}"

        temp_service = TemporaryCredentialService(host=config.storage_host, bucket=config.bucket)
        issued = await temp_service.issue(
            org_id=test_org.id,
            storage_org_prefix=org_prefix,
            storage_allowed_paths=["test_flow_a"],
        )

        temp_gateway = StorageAdminGateway(
            host=config.storage_host,
            access_key=issued.access_key,
            secret_key=issued.secret_key,
        )
        sibling_policy = build_temporary_policy(
            bucket=config.bucket, allowed_folders={f"{org_prefix}/test_flow_b"}
        )

        try:
            with pytest.raises(TemporaryCredentialIssueError) as exc_info:
                await temp_gateway.create_service_account(
                    policy=sibling_policy, expiration=timedelta(hours=1)
                )
        finally:
            await temp_gateway.close()

        # Specifically the backend's access-denied response -- not just any
        # TemporaryCredentialIssueError (e.g. the backend being unreachable
        # would also raise that and must NOT be mistaken for a pass here).
        assert "AccessDenied" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_org_credential_can_mint_temporary_accounts(
        self, config, org_with_provisioned_credentials
    ):
        """Sanity check: the org-level credential itself CAN mint temporary
        accounts -- confirms the fixture/infrastructure work, so a failure
        in the Deny test above is the Deny statement, not a broken setup."""
        test_org = org_with_provisioned_credentials
        org_prefix = f"org_{test_org.id}"

        temp_service = TemporaryCredentialService(host=config.storage_host, bucket=config.bucket)
        issued = await temp_service.issue(
            org_id=test_org.id,
            storage_org_prefix=org_prefix,
            storage_allowed_paths=["sanity_check_folder"],
        )

        assert len(issued.access_key) == 20
        assert len(issued.secret_key) == 40
