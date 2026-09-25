"""
Integration test against a REAL OpenSearch instance - requires
`docker compose -f docker-compose.yaml --env-file ./.env up -d --build
auditor opensearch` (see docs/auditor's dev guide) to be running first. Skipped automatically if unreachable, so
the plain unit-test suite (test_query_language.py /
test_opensearch_query_compiler.py) is never blocked by this file.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.core import settings
from app.db.opensearch_client import build_opensearch_client
from app.domains.base import DEFAULT_SCOPING, BaseScopeArgs, ScopedQueryBuilder
from app.domains.sessions.computed import SESSIONS_COMPUTED
from app.domains.sessions.fields import SESSIONS_FIELDS
from app.domains.sessions.index import SESSIONS_INDEX
from app.index_setup import runner as index_setup_runner
from app.repositories.opensearch_repository import OpenSearchAuditRepository
from app.repositories.compiler import QueryCompiler
from app.filtering.computed import split_computed_leaves
from app.filtering.query_language import parse_query
from app.services.duration_filter import apply_duration_filter
from src.shared.models import SessionAuditEvent

_compiler = QueryCompiler(SESSIONS_FIELDS, DEFAULT_SCOPING)
_DURATION_FIELD = SESSIONS_COMPUTED[0]


def compile_filters(node, *, org_id, retention_days):
    return _compiler.compile(node, org_id=org_id, retention_days=retention_days)


def split_duration_filter(node):
    """Adapts the old (remainder, DurationCondition | None) return shape to
    the current split_computed_leaves(node, computed=...) -> (remainder,
    {field_name: condition}) shape, for this file's own call sites."""
    remainder, conditions = split_computed_leaves(node, computed=SESSIONS_COMPUTED)
    return remainder, conditions.get("duration")


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
    await index_setup_runner.ensure_index(client, SESSIONS_INDEX)
    yield client
    await client.close()


@pytest.fixture
def repository(opensearch_client):
    return OpenSearchAuditRepository(
        opensearch_client, SESSIONS_INDEX, SessionAuditEvent
    )


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
        _DURATION_FIELD,
        duration_cond,
        ScopedQueryBuilder(DEFAULT_SCOPING, BaseScopeArgs(org_id=ORG_A, retention_days=0)),
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
        _DURATION_FIELD,
        duration_cond2,
        ScopedQueryBuilder(DEFAULT_SCOPING, BaseScopeArgs(org_id=ORG_A, retention_days=0)),
        size=50,
        cursor=None,
    )
    assert node_id not in {e.id for e in events2}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_numeric_flattened_filter_matches_docs_above_threshold(
    repository, opensearch_client
):
    """Regression test for the `params._source` bug: a `gt` filter on a
    `details.*` flat_object key must actually match documents whose value
    clears the threshold, and reject ones that don't or lack the key."""
    fixtures = [
        _event(name="above", details={"tokens_used": 6000}),
        _event(name="below", details={"tokens_used": 100}),
        _event(name="missing"),
    ]
    await repository.write_batch(fixtures)
    await opensearch_client.indices.refresh(index="audit_events")

    ast = {"field": "details.tokens_used", "op": "gt", "value": 5000}
    query = compile_filters(ast, org_id=ORG_A, retention_days=0)
    events, _ = await repository.query(query, cursor=None, size=50)

    names = {e.name for e in events}
    assert "above" in names
    assert "below" not in names
    assert "missing" not in names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_numeric_flattened_filter_matches_docs_at_deep_nesting(
    repository, opensearch_client
):
    """Regression test for the exists-guard bug: a `gt` filter on a
    `output.*` flat_object key nested 3+ levels deep (root + 2, e.g.
    `output.token_usage.completion_tokens`) must actually match documents
    whose value clears the threshold. Before the fix, the compiled query
    included a `{"exists": {"field": path}}` guard that OpenSearch's
    flat_object `exists` query only resolves correctly one level below the
    root, so it silently matched 0 docs for any deeper path regardless of
    the literal value or whether the key was present."""
    fixtures = [
        _event(name="above", output={"token_usage": {"completion_tokens": 303}}),
        _event(name="below", output={"token_usage": {"completion_tokens": 10}}),
        # leaf key absent, but the parent object is present
        _event(name="missing-leaf", output={"token_usage": {}}),
        # the whole `output` root is absent from the document - the
        # deep-path equivalent of doc[params.path] resolving against a
        # completely unindexed flat_object field, not just a missing leaf
        _event(name="missing-root"),
    ]
    await repository.write_batch(fixtures)
    await opensearch_client.indices.refresh(index="audit_events")

    ast = {
        "field": "output.token_usage.completion_tokens",
        "op": "gt",
        "value": 100,
    }
    query = compile_filters(ast, org_id=ORG_A, retention_days=0)
    events, _ = await repository.query(query, cursor=None, size=50)

    names = {e.name for e in events}
    assert "above" in names
    assert "below" not in names
    assert "missing-leaf" not in names
    assert "missing-root" not in names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_key_exists_matches_docs_with_deeply_nested_key_present(
    repository, opensearch_client
):
    """Same flat_object exists-depth bug, on `key_exists`: a 2+-level path
    used to silently match 0 docs regardless of whether the key was
    actually present."""
    fixtures = [
        _event(name="present", output={"token_usage": {"completion_tokens": 42}}),
        # leaf key absent, but the parent object is present
        _event(name="missing-leaf", output={"token_usage": {}}),
        # the whole `output` root is absent from the document
        _event(name="missing-root"),
        # the root carries other leaf values but not this key - the only
        # fixture that tells a real per-key check apart from "is the root
        # object non-empty?", which is what a doc[path]-based check answers
        _event(name="other-keys-only", output={"summary": "done", "retries": 2}),
    ]
    await repository.write_batch(fixtures)
    await opensearch_client.indices.refresh(index="audit_events")

    ast = {"field": "output.token_usage.completion_tokens", "op": "key_exists"}
    query = compile_filters(ast, org_id=ORG_A, retention_days=0)
    events, _ = await repository.query(query, cursor=None, size=50)

    names = {e.name for e in events}
    assert "present" in names
    assert "missing-leaf" not in names
    assert "missing-root" not in names
    assert "other-keys-only" not in names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_key_not_exists_matches_only_docs_missing_the_deeply_nested_key(
    repository, opensearch_client
):
    """Negated direction: `must_not`-wrapped `exists` on a 2+-level path
    used to match every document. Must match only docs genuinely missing
    the key."""
    fixtures = [
        _event(name="present", output={"token_usage": {"completion_tokens": 42}}),
        _event(name="missing-leaf", output={"token_usage": {}}),
        _event(name="missing-root"),
        # see the sibling key_exists test - a non-empty root missing this one
        # key is the case a doc[path]-based check gets wrong
        _event(name="other-keys-only", output={"summary": "done", "retries": 2}),
    ]
    await repository.write_batch(fixtures)
    await opensearch_client.indices.refresh(index="audit_events")

    ast = {"field": "output.token_usage.completion_tokens", "op": "key_not_exists"}
    query = compile_filters(ast, org_id=ORG_A, retention_days=0)
    events, _ = await repository.query(query, cursor=None, size=50)

    names = {e.name for e in events}
    assert "present" not in names
    assert "missing-leaf" in names
    assert "missing-root" in names
    assert "other-keys-only" in names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_survives_a_document_with_out_of_literal_status(
    repository, opensearch_client
):
    """A document with a `status` outside the SessionAuditEvent Literal
    (written directly via the client, bypassing the model - this is
    exactly the "legacy/manually-written document" scenario the fix
    protects against) must not 500 the search; the other valid document on
    the same page must still come back."""
    good = _event(name="good-status-doc")
    await repository.write_batch([good])

    bad_source = good.model_copy(update={"id": str(uuid.uuid4())}).model_dump(
        mode="json"
    )
    bad_source["status"] = "warning"
    bad_source["name"] = "bad-status-doc"
    await opensearch_client.index(
        index="audit_events", id=bad_source["id"], body=bad_source
    )
    await opensearch_client.indices.refresh(index="audit_events")

    ast = {"field": "name", "op": "contains", "value": "status-doc"}
    query = compile_filters(ast, org_id=ORG_A, retention_days=0)
    events, _ = await repository.query(query, cursor=None, size=50)

    names = {e.name for e in events}
    assert "good-status-doc" in names
    assert "bad-status-doc" not in names


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
