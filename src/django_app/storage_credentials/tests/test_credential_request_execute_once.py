"""Fail-closed and execute-once guarantees for the trusted-scope handoff,
tested against the classes that actually implement them:
`StorageCredentialRequestConsumer._issue_for` (GETDEL on the scope key --
mint never happens without a published scope) and
`StorageCredentialResultListener._handle` (GETDEL on the lease key -- a
duplicate `code_results` delivery revokes at most once).

The test plan named `TemporaryCredentialService` as the owner of these
guarantees; reading the real implementation shows they live here instead
(see the note in `test_temporary_credential_service.py`). Redis is a mock,
not fakeredis: only `getdel`/`set`/`rpush`/`expire` are exercised, and
asserting on the mock's call arguments is a more direct check of "was the
gateway/service actually invoked" than round-tripping through a real key
store would be.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from storage_credentials.constants import TEMPORARY_CREDENTIAL_TTL_SECONDS_MAX
from storage_credentials.exceptions import CredentialScopeValidationError
from storage_credentials.redis import keys
from storage_credentials.redis.request_consumer import StorageCredentialRequestConsumer
from storage_credentials.redis.result_listener import StorageCredentialResultListener
from storage_credentials.services.temporary_credential_service import IssuedCredential

EXECUTION_ID = "exec-1"


@pytest.fixture
def redis_client():
    client = MagicMock()
    client.getdel = AsyncMock()
    client.get = AsyncMock()
    client.set = AsyncMock()
    client.rpush = AsyncMock()
    client.expire = AsyncMock()
    return client


@pytest.fixture
def credential_service():
    service = MagicMock()
    service.issue = AsyncMock(
        return_value=IssuedCredential(access_key="temp-ak", secret_key="temp-sk")
    )
    service.revoke = AsyncMock()
    return service


@pytest.fixture
def consumer(redis_client, credential_service):
    return StorageCredentialRequestConsumer(
        stream_client=MagicMock(),
        redis_client=redis_client,
        credential_service=credential_service,
    )


@pytest.fixture
def listener(redis_client, credential_service):
    return StorageCredentialResultListener(
        redis_client=redis_client, credential_service=credential_service
    )


@pytest.mark.asyncio
async def test_issue_for_with_no_published_scope_never_calls_mint(
    consumer, redis_client, credential_service
):
    redis_client.getdel.return_value = None
    # Genuinely nobody is in-progress for this execution_id -- this is a
    # true "scope never published" case, not a redelivery race.
    redis_client.get.return_value = None

    await consumer._issue_for(EXECUTION_ID)

    credential_service.issue.assert_not_awaited()
    error_payload = json.loads(redis_client.rpush.await_args.args[1])
    assert error_payload == {"error": "scope_not_published"}


@pytest.mark.asyncio
async def test_issue_for_with_invalid_scope_never_calls_mint(
    consumer, redis_client, credential_service
):
    redis_client.getdel.return_value = json.dumps(
        {
            "org_id": 1,
            "storage_org_prefix": "org_1",
            "storage_allowed_paths": ["../etc"],
        }
    )
    credential_service.issue.side_effect = CredentialScopeValidationError("bad scope")

    await consumer._issue_for(EXECUTION_ID)

    error_payload = json.loads(redis_client.rpush.await_args.args[1])
    assert error_payload == {"error": "bad scope"}
    # `set` is awaited exactly once here -- for the in-progress marker,
    # written right after winning the GETDEL and before scope validation
    # runs. No lease is ever set for a request that never minted anything.
    redis_client.set.assert_awaited_once()
    set_keys = [call.args[0] for call in redis_client.set.await_args_list]
    assert set_keys == [keys.in_progress_key(EXECUTION_ID)]
    assert keys.lease_key(EXECUTION_ID) not in set_keys


@pytest.mark.asyncio
async def test_issue_for_success_sets_a_lease_and_responds(
    consumer, redis_client, credential_service
):
    redis_client.getdel.return_value = json.dumps(
        {"org_id": 1, "storage_org_prefix": "org_1", "storage_allowed_paths": ["flowA"]}
    )

    await consumer._issue_for(EXECUTION_ID)

    credential_service.issue.assert_awaited_once_with(
        org_id=1, storage_org_prefix="org_1", storage_allowed_paths=["flowA"]
    )
    # `set` is awaited twice: once for the in-progress marker (right after
    # winning the GETDEL), once for the lease (after a successful mint).
    assert redis_client.set.await_count == 2
    set_keys = [call.args[0] for call in redis_client.set.await_args_list]
    assert set_keys == [
        keys.in_progress_key(EXECUTION_ID),
        keys.lease_key(EXECUTION_ID),
    ]
    lease_key, lease_value = redis_client.set.await_args.args[:2]
    assert lease_key == keys.lease_key(EXECUTION_ID)
    assert json.loads(lease_value) == {"org_id": 1, "access_key": "temp-ak"}
    assert (
        redis_client.set.await_args.kwargs["ex"] == TEMPORARY_CREDENTIAL_TTL_SECONDS_MAX
    )
    response_payload = json.loads(redis_client.rpush.await_args.args[1])
    assert response_payload == {"access_key": "temp-ak", "secret_key": "temp-sk"}


@pytest.mark.asyncio
async def test_result_listener_revokes_once_on_first_delivery(
    listener, redis_client, credential_service
):
    redis_client.getdel.return_value = json.dumps(
        {"org_id": 1, "access_key": "temp-ak"}
    )

    await listener._handle(json.dumps({"execution_id": EXECUTION_ID}))

    credential_service.revoke.assert_awaited_once_with(org_id=1, access_key="temp-ak")


@pytest.mark.asyncio
async def test_result_listener_is_a_silent_noop_on_duplicate_delivery(
    listener, redis_client, credential_service
):
    """The lease key is GETDEL'd: a duplicate `code_results` message for the
    same execution_id finds it already gone and must not call `revoke` a
    second time against an account that may already have been revoked by
    the first delivery, or by `TtlReconciliationService.sweep()`."""
    redis_client.getdel.return_value = None

    await listener._handle(json.dumps({"execution_id": EXECUTION_ID}))

    credential_service.revoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_result_listener_second_call_after_the_lease_is_consumed_does_not_revoke_again(
    listener, redis_client, credential_service
):
    redis_client.getdel.return_value = json.dumps(
        {"org_id": 1, "access_key": "temp-ak"}
    )
    await listener._handle(json.dumps({"execution_id": EXECUTION_ID}))
    credential_service.revoke.assert_awaited_once()

    redis_client.getdel.return_value = None
    await listener._handle(json.dumps({"execution_id": EXECUTION_ID}))

    credential_service.revoke.assert_awaited_once()
