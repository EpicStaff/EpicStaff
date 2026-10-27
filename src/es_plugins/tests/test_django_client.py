import json
from datetime import UTC, datetime

import httpx
import pytest
from src.shared.models.plugin_nodes import HookResult, NodeReport

from es_plugins.agent.django_client import DjangoNodeClient, NodeApiError, top_level_member
from tests.helpers import (
    API_URL,
    HOOK_ASSERTION,
    NODE_KEY,
    FakeDjango,
    desired_state,
    hook_body,
    hook_invocation,
    hook_job,
    placement,
    runtime_file_document,
)


def client_answering(handler) -> DjangoNodeClient:
    return DjangoNodeClient(API_URL, NODE_KEY, transport=httpx.MockTransport(handler))


@pytest.fixture
async def django():
    fake = FakeDjango()
    client = DjangoNodeClient(API_URL, NODE_KEY, transport=fake.transport)
    yield fake, client
    await client.aclose()


async def test_the_desired_state_is_fetched_once_and_then_answered_304_by_etag(django):
    fake, client = django
    fake.desired = desired_state([placement(b"package")])

    first = await client.fetch_desired_state()
    second = await client.fetch_desired_state()

    assert first == fake.desired
    assert second is None
    assert fake.requests[1].headers["If-None-Match"] == f'"{fake.desired.revision}"'
    assert all(
        request.headers["Authorization"] == f"PluginNodeKey {NODE_KEY}" for request in fake.requests
    )


async def test_a_newer_django_apps_extra_fields_are_ignored():
    document = json.loads(desired_state([placement(b"package")]).model_dump_json())
    document["added_later"] = True
    document["placements"][0]["runtime"]["added_later"] = 1
    client = client_answering(lambda request: httpx.Response(200, json=document))

    desired = await client.fetch_desired_state()

    assert desired.placements[0].runtime.port == 20001


async def test_a_wrong_node_key_is_not_transient(tmp_path):
    fake = FakeDjango()
    client = DjangoNodeClient(API_URL, "w" * 64, transport=fake.transport)

    with pytest.raises(NodeApiError) as refused:
        await client.fetch_desired_state()

    assert (refused.value.status, refused.value.transient) == (401, False)
    await client.aclose()


async def test_an_unreachable_django_app_is_transient(django):
    fake, client = django
    fake.unavailable = True

    with pytest.raises(NodeApiError) as failed:
        await client.fetch_desired_state()

    assert failed.value.transient


async def test_a_package_download_matches_the_desired_sha256(tmp_path, django):
    fake, client = django
    package_bytes = b"a package" * 1000
    desired = placement(package_bytes)
    fake.packages[desired.package.package_id] = package_bytes
    destination = tmp_path / "weather.esplugin"

    await client.download_package(desired.package, destination)

    assert destination.read_bytes() == package_bytes


async def test_a_package_whose_bytes_differ_is_refused_and_not_kept(tmp_path, django):
    fake, client = django
    desired = placement(b"the expected package")
    fake.packages[desired.package.package_id] = b"another package!!!!!"
    destination = tmp_path / "weather.esplugin"

    with pytest.raises(NodeApiError, match="sha256") as refused:
        await client.download_package(desired.package, destination)

    assert not refused.value.transient
    assert list(tmp_path.iterdir()) == []


async def test_a_package_larger_than_announced_is_cut_off(tmp_path):
    desired = placement(b"small")
    client = client_answering(lambda request: httpx.Response(200, content=b"small" * 100))

    with pytest.raises(NodeApiError, match="larger than"):
        await client.download_package(desired.package, tmp_path / "weather.esplugin")

    assert list(tmp_path.iterdir()) == []


async def test_the_runtime_file_is_passed_on_byte_for_byte_with_unknown_fields():
    document = runtime_file_document()
    document["added_by_a_newer_epicstaff"] = {"kept": True}
    body = (
        '{"placement_id": 7,\n "credentials_revision": "' + "c" * 64 + '", "settings_revision": 5,'
        ' "runtime_file":  ' + json.dumps(document, indent=1) + "\n}"
    ).encode()
    client = client_answering(lambda request: httpx.Response(200, content=body))

    fetched = await client.fetch_runtime_credentials(7)

    assert fetched.runtime_file == json.dumps(document, indent=1).encode()
    assert fetched.credentials.settings_revision == 5


async def test_an_invalid_runtime_file_is_refused_without_its_values_in_the_message():
    document = runtime_file_document(secret_settings=["secret-token-value"])
    body = {
        "placement_id": 7,
        "credentials_revision": "c" * 64,
        "settings_revision": "secret-in-a-number",
        "runtime_file": document,
    }
    client = client_answering(lambda request: httpx.Response(200, json=body))

    with pytest.raises(NodeApiError) as refused:
        await client.fetch_runtime_credentials(7)

    message = str(refused.value)
    assert "settings_revision:" in message
    assert "runtime_file.secret_settings:" in message
    assert "secret-token-value" not in message
    assert "secret-in-a-number" not in message
    assert refused.value.transient is False


def test_a_member_is_found_whatever_comes_before_it():
    document = b'{"a": {"runtime_file": 1}, "b": "x\\"y", "runtime_file": [1, {"z": null}] }'

    assert top_level_member(document, "runtime_file") == b'[1, {"z": null}]'


def test_a_missing_member_is_an_error():
    with pytest.raises(NodeApiError, match="has no runtime_file"):
        top_level_member(b'{"placement_id": 7}', "runtime_file")


async def test_the_report_is_posted_as_json(django):
    fake, client = django
    report = NodeReport(
        format=1, agent_version="0.1.0", reported_at=datetime.now(UTC), placements=[]
    )

    await client.send_report(report)

    assert fake.reports[0]["agent_version"] == "0.1.0"
    assert fake.requests[0].headers["Content-Type"] == "application/json"


async def test_a_desired_placement_lists_its_pending_hook_jobs(django):
    fake, client = django
    fake.desired = desired_state(
        [placement(b"package", hook_jobs=[hook_job(41, 3), hook_job(42, 4)])]
    )

    desired = await client.fetch_desired_state()

    assert [(job.job_id, job.kind, job.organization_id) for job in desired.placements[0].hook_jobs] == [
        (41, "install", 3),
        (42, "install", 4),
    ]


async def test_a_desired_placement_from_a_django_app_without_hooks_has_none():
    document = json.loads(desired_state([placement(b"package")]).model_dump_json())
    del document["placements"][0]["hook_jobs"]
    client = client_answering(lambda request: httpx.Response(200, json=document))

    desired = await client.fetch_desired_state()

    assert desired.placements[0].hook_jobs == []


async def test_a_claim_is_posted_for_the_job_and_answers_its_invocation(django):
    fake, client = django
    fake.hook_invocations[41] = {**hook_invocation(), "added_later": True}

    invocation = await client.claim_hook_job(41)

    claim = fake.requests[0]
    assert (claim.method, claim.url.path) == ("POST", "/api/plugin-nodes/self/hook-jobs/41/claim/")
    assert claim.headers["Authorization"] == f"PluginNodeKey {NODE_KEY}"
    assert (invocation.job_id, invocation.kind, invocation.attempt, invocation.organization_id) == (
        41,
        "install",
        1,
        3,
    )
    assert (invocation.assertion, invocation.body) == (HOOK_ASSERTION, hook_body())


@pytest.mark.parametrize("status", [404, 409])
async def test_a_job_that_is_no_longer_pending_cannot_be_claimed(status):
    client = client_answering(lambda request: httpx.Response(status, json={"code": "x"}))

    assert await client.claim_hook_job(41) is None


@pytest.mark.parametrize(("status", "transient"), [(400, False), (401, False), (503, True)])
async def test_a_failed_claim_says_whether_to_try_again(status, transient):
    client = client_answering(lambda request: httpx.Response(status, json={"code": "x"}))

    with pytest.raises(NodeApiError) as failed:
        await client.claim_hook_job(41)

    assert (failed.value.status, failed.value.transient) == (status, transient)


async def test_a_claim_answered_for_another_job_is_refused():
    client = client_answering(lambda request: httpx.Response(200, json=hook_invocation(job_id=42)))

    with pytest.raises(NodeApiError, match="claimed hook job 41, got 42") as refused:
        await client.claim_hook_job(41)

    assert not refused.value.transient


async def test_an_invalid_invocation_is_refused_without_its_assertion_or_body_in_the_message():
    document = {**hook_invocation(), "timeout_seconds": 0, "kind": "uninstall"}
    client = client_answering(lambda request: httpx.Response(200, json=document))

    with pytest.raises(NodeApiError) as refused:
        await client.claim_hook_job(41)

    message = str(refused.value)
    assert "timeout_seconds:" in message and "kind:" in message
    assert HOOK_ASSERTION not in message
    assert "Acme" not in message


async def test_a_hook_result_is_posted_as_json_for_its_job(django):
    fake, client = django
    result = HookResult(
        attempt=2, outcome="failed", error="HTTP 500", http_status=500, duration_ms=1234
    )

    await client.send_hook_result(41, result)

    request = fake.requests[0]
    assert request.url.path == "/api/plugin-nodes/self/hook-jobs/41/result/"
    assert request.headers["Content-Type"] == "application/json"
    assert fake.hook_results == [
        (
            41,
            {
                "attempt": 2,
                "outcome": "failed",
                "error": "HTTP 500",
                "http_status": 500,
                "duration_ms": 1234,
            },
        )
    ]


@pytest.mark.parametrize(("status", "transient"), [(409, False), (400, False), (502, True)])
async def test_a_refused_hook_result_says_whether_to_try_again(django, status, transient):
    fake, client = django
    fake.failing_result_posts, fake.failing_result_status = 1, status

    with pytest.raises(NodeApiError) as refused:
        await client.send_hook_result(41, HookResult(attempt=1, outcome="succeeded", duration_ms=1))

    assert (refused.value.status, refused.value.transient) == (status, transient)
