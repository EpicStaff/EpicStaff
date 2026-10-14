"""Who may call the audit routes, checked over HTTP against the real app with real tokens.

No lifespan runs, so no OpenSearch or Redis is needed: every request here is meant to
stop at the authorization gate.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests._auth import auth

pytestmark = pytest.mark.asyncio

SEARCH = ("POST", "/api/audit/sessions/search")
EXPORT_ENDPOINTS = [
    ("POST", "/api/audit/sessions/export"),
    ("GET", "/api/audit/sessions/export"),
    ("GET", "/api/audit/sessions/export/some-job"),
    ("DELETE", "/api/audit/sessions/export/some-job"),
]


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


async def _call(client, endpoint, headers):
    method, path = endpoint
    return await client.request(method, path, headers=headers, json={})


@pytest.mark.parametrize(
    "headers",
    [
        {},
        auth(iss="someone-else"),
        auth(iss=None),
        auth(exp=None),
        auth(retention_days=None),
    ],
    ids=["no-token", "wrong-issuer", "missing-issuer", "missing-expiry", "missing-retention"],
)
async def test_invalid_token_is_rejected_with_401(client, headers):
    response = await _call(client, SEARCH, headers)

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("endpoint", "headers"),
    [
        (SEARCH, auth(AUDIT=None, BILLING=["read"])),
        (SEARCH, auth(AUDIT=None, actions=["read"])),
        (SEARCH, auth(AUDIT="read")),
        *[(endpoint, auth(AUDIT=["read"])) for endpoint in EXPORT_ENDPOINTS],
        (EXPORT_ENDPOINTS[0], auth(AUDIT=None, BILLING=["export"])),
    ],
    ids=[
        "search-grant-on-another-resource",
        "search-legacy-flat-actions-claim",
        "search-malformed-resource-claim",
        "start-export-with-read-only",
        "list-exports-with-read-only",
        "download-export-with-read-only",
        "delete-export-with-read-only",
        "export-grant-on-another-resource",
    ],
)
async def test_token_without_the_routes_grant_is_rejected_with_403(client, endpoint, headers):
    response = await _call(client, endpoint, headers)

    assert response.status_code == 403
