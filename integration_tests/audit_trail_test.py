"""
Running these
-------------

The audit stack lives behind the `audit` compose profile, so every test here
skips (rather than fails) when auditor isn't reachable. Bring the stack up
from `src/` with:

    docker compose -f docker-compose.yaml -f docker-compose.override.yaml \
        -f docker-compose.dev.yaml --env-file ./.dev.env --profile audit up -d

`AUDIT_TRAIL_ENABLED=True` must also be set for the producer side, otherwise
crew's AuditClient no-ops and `test_session_run_produces_audit_trail` fails
with an empty trail (which is exactly what it should report).

Nothing here reads integration_tests/.env - that file is consumed by the
dockerized test stack, not by a host-side pytest run. So when running from
the host, pass the audit config explicitly or most of this file silently
skips:

    AUDITOR_INGEST_API_KEY=<src/.dev.env value> \
    JWT_SECRET=<src/.dev.env value> \
    pytest audit_trail_test.py -rs

`AUDITOR_INGEST_API_KEY` gates the direct-ingest tests and `JWT_SECRET` gates
the forged-claim tests; without them only the real-producer and token-minting
tests run. Use `-rs` to see exactly what skipped and why. `AUDIT_TEST_ORG_ID`
optionally pins the org instead of taking the first one from the admin
listing.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from loguru import logger

from utils.audit_utils import (
    auditor_is_available,
    create_export_job,
    decode_jwt_payload,
    forge_audit_token,
    get_audit_org_id,
    get_session_tree,
    ingest_events,
    ingest_key_configured,
    jwt_secret_configured,
    make_audit_event,
    mint_audit_token,
    query_sessions,
    synthetic_session_id,
    wait_for_audit_event_id,
    wait_for_audit_tree,
    wait_for_export,
)
from utils.variables import AUDIT_TOKEN_TTL_SECONDS, AUDITOR_URL
from utils.cleaning_utils import delete_graph, delete_session
from utils.utils import (
    create_edge,
    create_end_node,
    create_graph,
    create_python_node,
    create_start_node,
    ensure_services_ready,
    run_session,
    set_active_organization,
    wait_for_results_sse,
)

pytestmark = pytest.mark.skipif(
    not auditor_is_available(),
    reason="auditor is not reachable - start the stack with --profile audit",
)


@pytest.fixture(scope="module")
def org_id() -> int:
    ensure_services_ready()
    resolved = get_audit_org_id()
    # Graph/session endpoints resolve an active organization from this header
    # and reject requests without it.
    set_active_organization(resolved)
    yield resolved
    set_active_organization(None)


@pytest.fixture(scope="module")
def read_export_token(org_id) -> str:
    """A real Django-minted token - the genuine RBAC path."""
    body = mint_audit_token(org_id)
    return body["token"]


# --------------------------------------------------------------------------
# token minting (django_app side)
# --------------------------------------------------------------------------


def test_audit_token_carries_rbac_derived_claims(org_id):
    """POST /api/audit/token/ turns effective AUDIT permissions into claims."""
    body = mint_audit_token(org_id)

    assert body["expires_in"] == AUDIT_TOKEN_TTL_SECONDS, (
        f"Token TTL should match AUDIT_TOKEN_TTL_SECONDS ({AUDIT_TOKEN_TTL_SECONDS}s)"
    )

    claims = decode_jwt_payload(body["token"])
    assert claims["org_id"] == org_id
    assert "read" in claims["actions"], (
        "The suite's admin should hold AUDIT:read via the seeded Org Admin role"
    )
    assert set(claims["actions"]) <= {"read", "export"}, (
        f"Unexpected action in claims: {claims['actions']}"
    )
    assert isinstance(claims["retention_days"], int)
    assert claims["exp"] - claims["iat"] == AUDIT_TOKEN_TTL_SECONDS


# --------------------------------------------------------------------------
# auth gating (auditor side)
# --------------------------------------------------------------------------


def test_query_rejects_missing_and_malformed_tokens():
    unauthenticated = requests.get(f"{AUDITOR_URL}/api/audit/sessions", timeout=30)
    assert unauthenticated.status_code == 401, "An unauthenticated read must be refused"

    assert query_sessions("not-a-jwt").status_code == 401
    assert query_sessions("").status_code == 401


@pytest.mark.skipif(not jwt_secret_configured(), reason="JWT_SECRET not configured")
def test_export_requires_the_export_action(org_id):
    """read and export are independently gated by the token's actions claim."""
    read_only = forge_audit_token(org_id, actions=["read"])

    assert query_sessions(read_only).status_code == 200, "read-only must still read"
    assert create_export_job(read_only).status_code == 403, (
        "A token without the export action must not be able to start an export"
    )

    exporter = forge_audit_token(org_id, actions=["read", "export"])
    assert create_export_job(exporter).status_code == 200


@pytest.mark.skipif(not ingest_key_configured(), reason="AUDITOR_INGEST_API_KEY not set")
def test_ingest_requires_the_api_key(org_id):
    event = make_audit_event(
        org_id=org_id, session_id=synthetic_session_id(), event_id=str(uuid.uuid4())
    )

    assert ingest_events([event], api_key="").status_code == 401
    assert ingest_events([event], api_key="wrong-key").status_code == 401
    assert ingest_events([event]).status_code == 200


# --------------------------------------------------------------------------
# org isolation
# --------------------------------------------------------------------------


@pytest.mark.skipif(not jwt_secret_configured(), reason="JWT_SECRET not configured")
@pytest.mark.skipif(not ingest_key_configured(), reason="AUDITOR_INGEST_API_KEY not set")
def test_events_are_not_readable_across_organizations(org_id):
    """Every query is org-scoped by the token's own org_id claim."""
    session_id = synthetic_session_id()
    event_id = str(uuid.uuid4())
    assert ingest_events(
        [make_audit_event(org_id=org_id, session_id=session_id, event_id=event_id)]
    ).status_code == 200

    own_token = forge_audit_token(org_id, actions=["read"])
    wait_for_audit_event_id(own_token, session_id, event_id)

    foreign_org_id = org_id + 10_000  # an org that owns nothing
    foreign_token = forge_audit_token(foreign_org_id, actions=["read"])

    response = get_session_tree(foreign_token, session_id)
    assert response.status_code == 200
    assert response.json()["items"] == [], (
        "A token scoped to another org must not see this org's audit rows"
    )


# --------------------------------------------------------------------------
# retention
# --------------------------------------------------------------------------


@pytest.mark.skipif(not jwt_secret_configured(), reason="JWT_SECRET not configured")
@pytest.mark.skipif(not ingest_key_configured(), reason="AUDITOR_INGEST_API_KEY not set")
def test_retention_hides_old_events_without_deleting_them(org_id):
    """
    EST-3341: retention is a query-time window, not deletion. The same row
    must disappear under a short window and reappear under an unlimited one.
    Driven with forged tokens carrying explicit retention_days so the org's
    real configuration is never mutated by this test.
    """
    session_id = synthetic_session_id()
    old_event_id = str(uuid.uuid4())

    assert ingest_events(
        [
            make_audit_event(
                org_id=org_id,
                session_id=session_id,
                event_id=old_event_id,
                event_time=datetime.now(timezone.utc) - timedelta(days=30),
            )
        ]
    ).status_code == 200

    unlimited = forge_audit_token(org_id, actions=["read"], retention_days=0)
    wait_for_audit_event_id(unlimited, session_id, old_event_id)

    windowed = forge_audit_token(org_id, actions=["read"], retention_days=7)
    windowed_items = get_session_tree(windowed, session_id).json()["items"]
    assert old_event_id not in [i["id"] for i in windowed_items], (
        "A 30-day-old event must fall outside a 7-day retention window"
    )

    # ...and it is only hidden: the unlimited token still sees it.
    still_there = get_session_tree(unlimited, session_id).json()["items"]
    assert old_event_id in [i["id"] for i in still_there], (
        "Retention must filter at query time, never delete the underlying row"
    )


# --------------------------------------------------------------------------
# ingest semantics
# --------------------------------------------------------------------------


@pytest.mark.skipif(not jwt_secret_configured(), reason="JWT_SECRET not configured")
@pytest.mark.skipif(not ingest_key_configured(), reason="AUDITOR_INGEST_API_KEY not set")
def test_resending_the_same_event_id_does_not_duplicate_it(org_id):
    """
    Dedup is by explicit document _id, so the client's retry path is safe:
    a re-sent batch overwrites in place instead of duplicating.
    """
    session_id = synthetic_session_id()
    event_id = str(uuid.uuid4())
    event = make_audit_event(org_id=org_id, session_id=session_id, event_id=event_id)

    assert ingest_events([event]).status_code == 200
    token = forge_audit_token(org_id, actions=["read"])
    wait_for_audit_event_id(token, session_id, event_id)

    assert ingest_events([event]).status_code == 200
    assert ingest_events([event]).status_code == 200

    items = wait_for_audit_tree(token, session_id, min_items=1)
    matching = [i for i in items if i["id"] == event_id]
    assert len(matching) == 1, f"Expected exactly one row for {event_id}, got {len(matching)}"


@pytest.mark.skipif(not jwt_secret_configured(), reason="JWT_SECRET not configured")
@pytest.mark.skipif(not ingest_key_configured(), reason="AUDITOR_INGEST_API_KEY not set")
def test_free_text_search_reaches_into_unredacted_payloads(org_id):
    """
    The reason this feature stores audit data in OpenSearch at all: search
    has to reach inside the unredacted input/output JSON, not just match
    structured columns.
    """
    session_id = synthetic_session_id()
    event_id = str(uuid.uuid4())
    needle = f"est3322needle{uuid.uuid4().hex[:8]}"

    assert ingest_events(
        [
            make_audit_event(
                org_id=org_id,
                session_id=session_id,
                event_id=event_id,
                input={"prompt": f"please find {needle} inside this text"},
            )
        ]
    ).status_code == 200

    token = forge_audit_token(org_id, actions=["read"])
    wait_for_audit_event_id(token, session_id, event_id)

    response = query_sessions(token, search=needle)
    assert response.status_code == 200
    found = [i["id"] for i in response.json()["items"]]
    assert event_id in found, f"Free-text search for {needle!r} did not find the event"


# --------------------------------------------------------------------------
# the real producer path
# --------------------------------------------------------------------------


def test_session_run_produces_audit_trail(org_id, read_export_token):
    """
    Run a genuine session and assert crew emitted a correct audit tree for
    it: one kind='session' root plus at least one kind='node' row, org-scoped,
    with the flow name and the node's captured output.
    """
    ensure_services_ready()

    graph_id = create_graph("Audit trail graph")
    session_id = None
    try:
        start_node_id = create_start_node(graph_id=graph_id)
        python_node_id = create_python_node(
            graph=graph_id,
            node_name="audit_probe_node",
            code=(
                "def main(*args, **kwargs):\n"
                "    return {'result': 'audited-ok', 'hash': 'deadbeef'}\n"
            ),
            input_map={},
            output_variable_path="variables",
        )
        end_node_id = create_end_node(graph_id=graph_id)
        create_edge(
            start_node_id=start_node_id, end_node_id=python_node_id, graph=graph_id
        )
        create_edge(start_node_id=python_node_id, end_node_id=end_node_id, graph=graph_id)

        session_id = run_session(graph_id=graph_id)
        logger.info(f"Audit test session {session_id} started")
        wait_for_results_sse(session_id=session_id)

        # The session identity doc + "Session Start" land immediately (top of
        # run_session), well before the session finishes - wait specifically
        # for "Session End" too, or we'd assert on a session that's still
        # mid-run.
        items = wait_for_audit_tree(
            read_export_token,
            session_id,
            required_kinds={"session", "node"},
            required_event_names={"Session Start", "Session End"},
        )
        by_kind: dict[str, list[dict]] = {}
        for item in items:
            by_kind.setdefault(item["kind"], []).append(item)

        assert "session" in by_kind, f"No kind='session' row emitted. Kinds: {list(by_kind)}"
        assert "node" in by_kind, f"No kind='node' row emitted. Kinds: {list(by_kind)}"

        session_rows = by_kind["session"]
        assert len(session_rows) == 1, (
            f"Exactly one session root expected, got {len(session_rows)}"
        )
        session_row = session_rows[0]
        assert session_row["org_id"] == org_id
        assert session_row["session_id"] == session_id
        assert session_row["status"] is None, (
            "The session identity doc's status must stay None forever "
            "(write-once/no-edit hard rule) - the real outcome lives on "
            "the 'Session End' event instead, never on this doc"
        )
        assert session_row["parent_id"] == "", "The session root must have no parent"
        assert session_row["flow_name"], (
            "flow_name must be populated on the session row, not left blank"
        )

        # kind=node rows are direct children of the session.
        for node in by_kind.get("node", []):
            assert node["parent_id"] == session_row["id"], (
                f"node row {node['id']} is not chained to the session root"
            )
            assert node["org_id"] == org_id

        event_rows = by_kind.get("event", [])
        for item in event_rows:
            assert item["org_id"] == org_id

        # Session Start/End are the two events parented directly to the
        # session itself - everything else parents to a specific node instead
        # (checked below, once we've identified audit_probe_node's own row).
        session_start_events = [e for e in event_rows if e["name"] == "Session Start"]
        assert len(session_start_events) == 1, (
            f"Exactly one 'Session Start' event expected, got {len(session_start_events)}"
        )
        assert session_start_events[0]["parent_id"] == session_row["id"], (
            "'Session Start' must be parented directly to the session"
        )
        assert session_start_events[0]["status"] == "completed"

        session_end_events = [e for e in event_rows if e["name"] == "Session End"]
        assert len(session_end_events) == 1, (
            f"Exactly one 'Session End' event expected, got {len(session_end_events)}"
        )
        session_end = session_end_events[0]
        assert session_end["parent_id"] == session_row["id"], (
            "'Session End' must be parented directly to the session"
        )
        assert session_end["status"] == "completed"
        assert session_end["output"], "Session End must carry the final output"

        # crew suffixes node names with an execution counter
        # ("audit_probe_node #19"), so match on the declared name as a prefix.
        node_row = next(
            (n for n in by_kind["node"] if n["name"].startswith("audit_probe_node")),
            None,
        )
        assert node_row is not None, (
            f"No node row for audit_probe_node. Names: "
            f"{[n['name'] for n in by_kind['node']]}"
        )
        assert node_row["status"] is None, (
            "The node wrapper's status must stay None forever - the real "
            "outcome lives on the 'Finish' event instead, never on this doc "
            "(same write-once/no-edit rule as the session identity doc)"
        )

        # every event this node emitted (its "Start" marker + activity events
        # like python_stream/python) must be parented to the node's own id -
        # not flatly to the session - so a trace viewer can nest them under
        # the right node even though they're written before the node's
        # outcome row exists.
        node_events = [e for e in event_rows if e["name"] == node_row["name"]]
        assert node_events, f"No event rows found for node {node_row['name']}"
        for event in node_events:
            assert event["parent_id"] == node_row["id"], (
                f"event {event['id']} ({event['name']}) is not chained to its "
                f"owning node {node_row['id']}, got parent_id={event['parent_id']}"
            )

        finish_events = [
            e for e in node_events if e["details"].get("message_type") == "finish"
        ]
        assert len(finish_events) == 1, (
            f"Expected exactly one Finish event for {node_row['name']}, "
            f"got {len(finish_events)}"
        )
        finish_event = finish_events[0]
        assert finish_event["status"] == "completed"
        assert finish_event["output"], "Finish event must carry the node's output"

        start_events = [
            e for e in node_events if e["details"].get("message_type") == "start"
        ]
        assert len(start_events) == 1, (
            f"Expected exactly one Start event for {node_row['name']}, "
            f"got {len(start_events)}"
        )

        # the session must also be listed by the org-wide session browser
        listed = query_sessions(read_export_token)
        assert listed.status_code == 200
        assert session_id in [i["session_id"] for i in listed.json()["items"]], (
            "The finished session did not appear in GET /api/audit/sessions"
        )
    finally:
        if session_id is not None:
            try:
                delete_session(session_id)
            except Exception as e:
                logger.warning(f"session cleanup failed: {e}")
        try:
            delete_graph(graph_id)
        except Exception as e:
            logger.warning(f"graph cleanup failed: {e}")


@pytest.mark.skipif(not ingest_key_configured(), reason="AUDITOR_INGEST_API_KEY not set")
def test_export_returns_the_events_as_csv(org_id, read_export_token):
    """
    POST /api/audit/export starts an async job; polling it yields the CSV.
    A row is seeded first so the export is non-empty regardless of what else
    this org happens to hold (auditor emits an empty body for zero rows).
    """
    session_id = synthetic_session_id()
    event_id = str(uuid.uuid4())
    assert ingest_events(
        [make_audit_event(org_id=org_id, session_id=session_id, event_id=event_id)]
    ).status_code == 200
    wait_for_audit_event_id(read_export_token, session_id, event_id)

    created = create_export_job(read_export_token, export_format="csv", detail="base")
    assert created.status_code == 200

    result = wait_for_export(read_export_token, created.json()["job_id"])
    assert result.status_code == 200

    body = result.text
    header = body.splitlines()[0]
    for column in ("id", "org_id", "session_id", "kind", "status", "event_time"):
        assert column in header, f"CSV export header is missing {column!r}: {header}"
    assert event_id in body, "The seeded session row is missing from the CSV export"
