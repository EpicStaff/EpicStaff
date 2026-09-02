"""
Integration test against a REAL OpenSearch instance - requires
`docker compose -f docker-compose.yaml -f docker-compose.dev.yaml
--env-file ./.dev.env up -d --build auditor opensearch` (see docs/auditor's
dev guide) to be running first. Skipped automatically if unreachable, so
the plain unit-test suite (test_query_language.py /
test_opensearch_query_compiler.py) is never blocked by this file.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.core.settings import settings
from app.db.opensearch_client import build_opensearch_client
from app.index_setup import runner as index_setup_runner
from app.repositories.opensearch_repository import OpenSearchSessionAuditRepository
from app.repositories.opensearch_query_compiler import compile as compile_filters
from app.filtering.query_language import parse_query
from app.services.duration_filter import apply_duration_filter, split_duration_filter
from src.shared.models import SessionAuditEvent


@pytest_asyncio.fixture
async def opensearch_client():
    client = build_opensearch_client(settings)
    try:
        reachable = await client.ping()
    except Exception:
        reachable = False
    if not reachable:
        await client.close()
        pytest.skip("OpenSearch is not reachable - bring up the dev stack first")
    await index_setup_runner.ensure_session_audit_index(client)
    yield client
    await client.close()


@pytest.fixture
def repository(opensearch_client):
    return OpenSearchSessionAuditRepository(opensearch_client)


ORG_A, ORG_B = 90001, 90002


def _event(**overrides) -> SessionAuditEvent:
    base = dict(
        id=str(uuid.uuid4()),
        org_id=ORG_A,
        kind="event",
        parent_id="",
        session_id=1,
        name="",
        status="completed",
        event_time=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return SessionAuditEvent(**base)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mixed_query_scopes_by_org_and_sorts_fixed(repository, opensearch_client):
    now = datetime.now(timezone.utc)
    node_id = str(uuid.uuid4())
    fixtures = [
        _event(
            kind="node",
            id=node_id,
            org_id=ORG_A,
            name="WebSearchNode",
            status=None,
            event_time=now,
        ),
        _event(
            org_id=ORG_A,
            parent_id=node_id,
            name="WebSearchNode",
            status="failed",
            details={"message_type": "error", "tool": "Web Search Tool"},
            error="litellm.AuthenticationError: OpenAIException",
            event_time=now + timedelta(seconds=1),
        ),
        _event(org_id=ORG_B, name="OtherOrgNode", status="failed", event_time=now),
    ]
    await repository.write_batch(fixtures)
    await opensearch_client.indices.refresh(index="audit_events")

    ast = parse_query('status = "failed" and Error : "AuthenticationError"')
    query = compile_filters(ast, org_id=ORG_A, retention_days=0)
    events, _ = await repository.query(query, cursor=None, size=50)

    assert all(e.org_id == ORG_A for e in events)
    assert any(e.status == "failed" for e in events)
    times = [e.event_time for e in events]
    assert times == sorted(times, reverse=True)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_duration_filter_includes_and_excludes_correctly(
    repository, opensearch_client
):
    node_id = str(uuid.uuid4())
    start_time = datetime.now(timezone.utc)
    fixtures = [
        _event(
            kind="node",
            id=node_id,
            org_id=ORG_A,
            name="SlowNode",
            status=None,
            event_time=start_time,
        ),
        _event(
            org_id=ORG_A,
            parent_id=node_id,
            name="SlowNode",
            details={"message_type": "start"},
            event_time=start_time,
        ),
        _event(
            org_id=ORG_A,
            parent_id=node_id,
            name="SlowNode",
            details={"message_type": "finish"},
            event_time=start_time + timedelta(seconds=3600),
        ),
    ]
    await repository.write_batch(fixtures)
    await opensearch_client.indices.refresh(index="audit_events")

    ast = {"field": "duration", "op": "gt", "value": 1800}
    remainder, duration_cond = split_duration_filter(ast)
    query = compile_filters(remainder, org_id=ORG_A, retention_days=0)
    events, _, partial = await apply_duration_filter(
        repository,
        query,
        duration_cond,
        org_id=ORG_A,
        retention_days=0,
        size=50,
        cursor=None,
    )
    assert any(e.id == node_id for e in events)
    assert not partial

    ast_excl = {"field": "duration", "op": "lt", "value": 10}
    remainder2, duration_cond2 = split_duration_filter(ast_excl)
    query2 = compile_filters(remainder2, org_id=ORG_A, retention_days=0)
    events2, _, _ = await apply_duration_filter(
        repository,
        query2,
        duration_cond2,
        org_id=ORG_A,
        retention_days=0,
        size=50,
        cursor=None,
    )
    assert node_id not in {e.id for e in events2}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_client_cannot_widen_org_scope(repository, opensearch_client):
    await repository.write_batch([_event(org_id=ORG_B, name="OrgBOnly")])
    await opensearch_client.indices.refresh(index="audit_events")

    # A crafted org_id leaf isn't even a legal field (rejected upstream by
    # validate_filter_node in the real route) - here we confirm compile()
    # itself never lets it override the injected clause even if validation
    # were bypassed.
    crafted = {"field": "org_id", "op": "equals", "value": ORG_B}
    query = compile_filters(crafted, org_id=ORG_A, retention_days=0)
    events, _ = await repository.query(query, cursor=None, size=50)
    assert all(e.org_id == ORG_A for e in events)
