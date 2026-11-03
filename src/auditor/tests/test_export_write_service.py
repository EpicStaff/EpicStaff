"""Writing an export file: what ends up in it and what the job records.

Runs the real search pipeline over an in-memory repository and a fake Redis; the
routes that start and serve the export are covered in test_export_routes.py.
"""

import csv
import io
import json
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis

import app.services.search_pipeline as search_pipeline
from app.core import settings
from app.domains.sessions.domain import SESSIONS
from app.repositories.opensearch_repository import OpenSearchAuditRepository
from app.domains.sessions.schemas import SessionExportRequest
from app.services.export_job_service import ExportJobService
from app.services.export_write_service import ExportWriteService
from app.services.search_pipeline import SearchPipeline
from src.shared.models import SessionAuditEvent
from tests._auth import DEFAULT_CLAIMS
from tests._fakes import InMemoryFakeRepository

pytestmark = pytest.mark.asyncio

NOW = datetime.now(timezone.utc)
JOB_ID = "job-1"


def _event(event_id: str = "evt-1", **fields) -> SessionAuditEvent:
    return SessionAuditEvent(
        **{
            "id": event_id,
            "session_id": 1,
            "kind": "event",
            "event_time": NOW,
            "org_id": DEFAULT_CLAIMS["org_id"],
            **fields,
        }
    )


@pytest_asyncio.fixture
async def job_service(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "AUDITOR_EXPORT_DATA_DIR", str(tmp_path))
    redis_client = FakeAsyncRedis(decode_responses=True)
    service = ExportJobService(redis_client)
    yield service
    await redis_client.aclose()


@pytest.fixture
def export(job_service, tmp_path):
    async def _export(events, repository=None, export_format="json", **body):
        await job_service.create_job(
            domain=SESSIONS.name, job_id=JOB_ID, org_id=DEFAULT_CLAIMS["org_id"],
            user_id=DEFAULT_CLAIMS["user_id"], ttl_seconds=3600, format=export_format,
        )
        await ExportWriteService.run_export(
            JOB_ID,
            SessionExportRequest(format=export_format, **body),
            DEFAULT_CLAIMS,
            SearchPipeline.from_domain(SESSIONS),
            repository or InMemoryFakeRepository(events),
            job_service,
        )
        export_file = tmp_path / f"{JOB_ID}.{export_format}"
        # read_bytes, not read_text: universal newlines would turn a "\r" cell into "\n".
        return export_file.read_bytes().decode("utf-8") if export_file.exists() else None

    return _export


async def _json_rows(export, events, **body) -> list[dict]:
    return json.loads(await export(events, **body))


async def _csv_rows(export, events) -> list[dict]:
    text = await export(events, export_format="csv")
    return list(csv.DictReader(io.StringIO(text, newline="")))


async def test_only_the_callers_org_is_exported(export):
    rows = await _json_rows(export, [_event("evt-1"), _event("evt-other-org", org_id=999)])

    assert [row["id"] for row in rows] == ["evt-1"]


@pytest.mark.parametrize(
    ("export_format", "expected_lines"),
    [
        ("json", ["[]"]),
        # The header is written before the scan, so the columns show even with no rows.
        (
            "csv",
            [",".join(name for name in SessionAuditEvent.model_fields if name != "retention_days")],
        ),
    ],
)
async def test_export_matching_nothing_is_still_a_valid_file(export, export_format, expected_lines):
    assert (await export([], export_format=export_format)).splitlines() == expected_lines


async def test_json_export_leaves_out_the_events_retention_days(export):
    [row] = await _json_rows(export, [_event(retention_days=90)])

    assert row["id"] == "evt-1"
    assert "retention_days" not in row


async def test_csv_export_has_no_retention_days_column(export):
    [row] = await _csv_rows(export, [_event(retention_days=90)])

    assert row["id"] == "evt-1"
    assert "retention_days" not in row


async def test_json_export_is_pretty_printed_utf8(export):
    text = await export([_event(flow_name="Vendor — Звіт")])

    assert text.startswith('[\n  {\n    "id": "evt-1",')
    assert '"flow_name": "Vendor — Звіт"' in text


def _session_tree(session_id: int = 100) -> list[SessionAuditEvent]:
    def tree_event(event_id, kind, seconds, parent_id=""):
        return _event(
            event_id, kind=kind, parent_id=parent_id, session_id=session_id,
            status="failed", event_time=NOW + timedelta(seconds=seconds),
        )

    return [
        tree_event(f"sess-{session_id}", "session", 0),
        tree_event(f"node-{session_id}", "node", 1, f"sess-{session_id}"),
        tree_event(f"evt-{session_id}-a", "event", 2, f"node-{session_id}"),
        tree_event(f"evt-{session_id}-b", "event", 3, f"node-{session_id}"),
    ]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            {"filters": {"field": "session_id", "op": "equals", "value": 100}},
            {"sess-100": True, "node-100": True, "evt-100-a": True, "evt-100-b": True},
        ),
        (
            {
                "filters": {"field": "id", "op": "equals", "value": "evt-100-a"},
                "match_scope": {"full_session_history": True},
            },
            {"sess-100": False, "node-100": False, "evt-100-a": True, "evt-100-b": False},
        ),
    ],
    ids=["no-match-scope", "full-session-history"],
)
async def test_export_flags_only_the_rows_the_filter_matched(export, body, expected):
    rows = await _json_rows(export, _session_tree(), **body)

    assert {row["id"]: row["filter_matched"] for row in rows} == expected


def _events(count: int) -> list[SessionAuditEvent]:
    return [
        _event(f"evt-{i}", session_id=i, event_time=NOW + timedelta(seconds=i))
        for i in range(count)
    ]


async def test_export_reads_every_page_without_duplicates_or_drops(export, monkeypatch):
    monkeypatch.setattr(search_pipeline, "SCAN_PAGE_SIZE", 2)

    rows = await _json_rows(export, _events(5))

    assert sorted(row["id"] for row in rows) == [f"evt-{i}" for i in range(5)]


async def test_export_stops_at_max_rows_and_records_the_truncation(
    export, job_service, monkeypatch
):
    monkeypatch.setattr(search_pipeline, "SCAN_PAGE_SIZE", 2)
    monkeypatch.setattr(settings, "AUDITOR_EXPORT_MAX_ROWS", 3)

    rows = await _json_rows(export, _events(5))

    assert len(rows) == 3
    assert (await job_service.get_job(JOB_ID))["truncated"] == "True"


async def test_full_session_history_across_pages_exports_each_row_once(export, monkeypatch):
    """Both matched events land on separate pages and expand to the same session tree."""
    monkeypatch.setattr(search_pipeline, "SCAN_PAGE_SIZE", 1)

    rows = await _json_rows(
        export,
        _session_tree(),
        filters={"field": "kind", "op": "equals", "value": "event"},
        match_scope={"full_session_history": True},
    )

    assert sorted(row["id"] for row in rows) == ["evt-100-a", "evt-100-b", "node-100", "sess-100"]


@pytest.mark.parametrize(
    "malicious_value",
    ['=HYPERLINK("http://evil")', "+1+1", "-2+3", "@SUM(A1)", "\t=1", "\r=1"],
)
async def test_csv_export_neutralizes_formula_leading_cells(export, malicious_value):
    (row,) = await _csv_rows(export, [_event(name=malicious_value)])

    assert row["name"] == f"'{malicious_value}"


async def test_csv_export_leaves_ordinary_cells_and_json_blobs_untouched(export):
    (row,) = await _csv_rows(export, [_event(name="Session Start", details={"answer": "=42"})])

    assert row["name"] == "Session Start"
    # A JSON blob starts with "{" and is not a formula, even if a nested value is.
    assert json.loads(row["details"]) == {"answer": "=42"}


async def test_json_export_is_not_formula_escaped(export):
    (row,) = await _json_rows(export, [_event(name="=1+1")])

    assert row["name"] == "=1+1"


async def test_failed_export_leaves_no_file_and_no_exception_text_in_the_job(
    export, job_service
):
    class ExplodingRepository:
        async def query(self, compiled_query, cursor=None, size=200):
            raise RuntimeError("secret internal detail /srv/path")

    assert await export([], repository=ExplodingRepository()) is None

    job = await job_service.get_job(JOB_ID)
    assert job["status"] == "failed"
    # Redis is reachable from the sandbox network, so the job hash must not hold it.
    assert "secret internal detail" not in json.dumps(job)


class _RecordingOpenSearchClient:
    def __init__(self, sources: list[dict]):
        self._hits = [{"_id": source["id"], "_source": source, "sort": [1, source["id"]]} for source in sources]
        self.searched_indices: list[str] = []

    async def search(self, index: str, body: dict) -> dict:
        self.searched_indices.append(index)
        return {"hits": {"hits": self._hits}}


async def test_export_reads_the_pattern(export):
    client = _RecordingOpenSearchClient([_event("evt-1").model_dump(mode="json")])
    repository = OpenSearchAuditRepository(client, SESSIONS.index, SessionAuditEvent)

    rows = json.loads(await export([], repository=repository))

    assert [row["id"] for row in rows] == ["evt-1"]
    assert client.searched_indices
    assert set(client.searched_indices) == {"audit_events-*"}
