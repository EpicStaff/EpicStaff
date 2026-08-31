"""`TemporaryCredentialService.issue()`/`revoke()` with a mocked
`MinioAdminGateway` and a mocked `OrgCredentialStore` -- no live MinIO, no DB.

Real behaviour, confirmed by reading `temporary_credential_service.py`
before writing these: `issue()` validates the trusted scope
(`CredentialScopeValidator`) *before* touching `org_credential_store` or the
MinIO gateway at all, so an invalid scope never reaches MinIO. `revoke()`
itself has no execute-once/dedup guard -- that GETDEL-based, "call the
issuer's gateway at most once per execution_id" guarantee actually lives one
layer up, in `storage_credentials/redis/request_consumer.py`
(`_issue_for`, GETDEL on the scope key) and
`storage_credentials/redis/result_listener.py` (`_handle`, GETDEL on the
lease key) -- not in this service. See
`test_credential_request_execute_once.py` for that behaviour tested against
the real owning classes; the plan's item #2 named this file but described
guarantees that are split across three classes in the actual implementation.
"""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from storage_credentials.exceptions import CredentialScopeValidationError
from storage_credentials.services import temporary_credential_service as tcs_module
from storage_credentials.services.org_credential_store import OrgMinioCredentials
from storage_credentials.services.temporary_credential_service import (
    TemporaryCredentialService,
)

ORG_CREDENTIALS = OrgMinioCredentials(access_key="org-ak", secret_key="org-sk")


@pytest.fixture
def fake_gateway():
    gateway = MagicMock()
    gateway.create_service_account = AsyncMock(return_value=("temp-ak", "temp-sk"))
    gateway.delete_service_account = AsyncMock()
    return gateway


@pytest.fixture
def service(monkeypatch, fake_gateway):
    monkeypatch.setattr(
        tcs_module, "MinioAdminGateway", MagicMock(return_value=fake_gateway)
    )
    monkeypatch.setattr(
        tcs_module.org_credential_store, "get", MagicMock(return_value=ORG_CREDENTIALS)
    )
    return TemporaryCredentialService(host="http://minio:9000", bucket="epicstaff")


@pytest.mark.asyncio
async def test_issue_mints_a_scoped_service_account(service, fake_gateway):
    issued = await service.issue(
        org_id=1, storage_org_prefix="org_1", storage_allowed_paths=["flowA"]
    )

    assert issued.access_key == "temp-ak"
    assert issued.secret_key == "temp-sk"
    fake_gateway.create_service_account.assert_awaited_once()
    expiration = fake_gateway.create_service_account.await_args.kwargs.get("expiration")
    assert expiration == timedelta(
        seconds=tcs_module.TEMPORARY_CREDENTIAL_TTL_SECONDS_DEFAULT
    )


@pytest.mark.asyncio
async def test_issue_with_invalid_scope_never_reaches_minio(service, fake_gateway):
    with pytest.raises(CredentialScopeValidationError):
        await service.issue(
            org_id=1, storage_org_prefix="org_1", storage_allowed_paths=["../etc"]
        )

    fake_gateway.create_service_account.assert_not_awaited()


@pytest.mark.asyncio
async def test_issue_with_missing_org_id_never_reaches_minio(service, fake_gateway):
    with pytest.raises(CredentialScopeValidationError):
        await service.issue(
            org_id=0, storage_org_prefix="org_1", storage_allowed_paths=["flowA"]
        )

    fake_gateway.create_service_account.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoke_calls_delete_service_account_once(service, fake_gateway):
    await service.revoke(org_id=1, access_key="temp-ak")

    fake_gateway.delete_service_account.assert_awaited_once_with("temp-ak")


@pytest.mark.asyncio
async def test_revoke_calling_twice_calls_gateway_twice(service, fake_gateway):
    """`TemporaryCredentialService.revoke()` itself is not execute-once -- it
    is a thin call-through to the gateway every time it is invoked. Calling
    it twice for the same access_key calls `delete_service_account` twice;
    dedup against a duplicate `code_results` delivery is the caller's
    (`StorageCredentialResultListener`) responsibility via the lease-key
    GETDEL, not this service's."""
    await service.revoke(org_id=1, access_key="temp-ak")
    await service.revoke(org_id=1, access_key="temp-ak")

    assert fake_gateway.delete_service_account.await_count == 2
