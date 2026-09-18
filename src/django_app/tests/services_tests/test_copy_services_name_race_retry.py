"""
EST-4002: bulk-copy races.

History of this file, since the fix went through two iterations before
landing on the real root cause:

1. First attempt: a bounded in-process retry (MAX_COPY_NAME_ATTEMPTS = 3) on
   IntegrityError. Insufficient — a large enough concurrent burst against the
   SAME source tool could exhaust the retry cap.
2. Second attempt: `select_for_update()` on the SOURCE row before generating
   the candidate name. This serializes concurrent copies of the SAME source
   row, but a live repro (bulk-copying several already-numbered siblings of
   one base tool, e.g. "qweqwe #2", "qweqwe #3", "qweqwe #333", all at once)
   showed it still failed most of the time. Root cause: `ensure_unique_identifier`
   strips any trailing "#N" suffix before computing the next free number, so
   DIFFERENT source rows ("qweqwe #2" and "qweqwe #3") both collapse to the
   same clean_base ("qweqwe") and race for the same generated name — a
   source-row lock does nothing for that, since the contended resource is the
   (org, clean_base) *name family*, not any single source row.
3. Current fix: a transaction-scoped Postgres advisory lock
   (`pg_advisory_xact_lock`) keyed on `(org_id, clean_base)`, held for the
   whole generate-name -> insert step. This serializes ALL concurrent copies
   that would land in the same name family, regardless of which source row
   each one started from.
"""

import queue
import threading
from typing import Callable

import pytest
from django.db import IntegrityError, connection

from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.rbac_models import Organization
from tables.services.copy_services.mcp_tool_copy_service import McpToolCopyService
from tables.services.copy_services.python_code_tool_copy_service import (
    PythonCodeToolCopyService,
)


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org CopyRaceRetry")


def _make_python_code_tool(org, name="RaceTool") -> PythonCodeTool:
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return PythonCodeTool.objects.create(
        name=name, description="desc", python_code=code, org=org
    )


def _make_mcp_tool(org, name="RaceMcp") -> McpTool:
    return McpTool.objects.create(
        name=name,
        org=org,
        transport="https://example.com/mcp",
        tool_name="some_tool",
    )


def _run_concurrently(targets: list[Callable]) -> list:
    """Runs each callable in `targets` in its own real thread (own DB
    connection each), synchronized to start together via a Barrier to
    maximize actual lock contention, and returns the collected per-thread
    results (return value, or the raised exception) in completion order.
    """
    n = len(targets)
    results: "queue.Queue" = queue.Queue()
    barrier = threading.Barrier(n)

    def _worker(target: Callable):
        try:
            barrier.wait(timeout=10)
            results.put(target())
        except Exception as exc:  # noqa: BLE001 - surfaced to the test via queue
            results.put(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=_worker, args=(t,)) for t in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    return [results.get(timeout=1) for _ in range(n)]


# ---- (a) concurrent copies of DIFFERENT source rows sharing a clean_base
# each get a unique name -- this is the actual production repro: bulk-copying
# several already-numbered siblings of the same base tool at once ----


@pytest.mark.django_db(transaction=True)
def test_python_code_tool_concurrent_copies_of_different_sources_sharing_clean_base():
    org = Organization.objects.create(name="Org PyToolNamespaceLock")
    # Three DIFFERENT source rows that all collapse to clean_base "Shared"
    # once ensure_unique_identifier strips the "#N" suffix -- mirrors the
    # real repro (source names "qweqwe #2" / "#3" / "#333").
    source_a = _make_python_code_tool(org, name="Shared #2")
    source_b = _make_python_code_tool(org, name="Shared #3")
    source_c = _make_python_code_tool(org, name="Shared #333")

    outcomes = _run_concurrently(
        [
            lambda: PythonCodeToolCopyService().copy(source_a).name,
            lambda: PythonCodeToolCopyService().copy(source_b).name,
            lambda: PythonCodeToolCopyService().copy(source_c).name,
        ]
    )

    for outcome in outcomes:
        assert not isinstance(outcome, Exception), outcome
    assert len(set(outcomes)) == 3  # every concurrent copy got a distinct name
    # existing numbers {2, 3, 333} -> the three lowest free slots are 4, 5, 6,
    # regardless of which thread's lock is acquired first.
    assert set(outcomes) == {"Shared #4", "Shared #5", "Shared #6"}


@pytest.mark.django_db(transaction=True)
def test_mcp_tool_concurrent_copies_of_different_sources_sharing_clean_base():
    org = Organization.objects.create(name="Org McpNamespaceLock")
    source_a = _make_mcp_tool(org, name="SharedMcp #2")
    source_b = _make_mcp_tool(org, name="SharedMcp #3")
    source_c = _make_mcp_tool(org, name="SharedMcp #333")

    outcomes = _run_concurrently(
        [
            lambda: McpToolCopyService().copy(source_a).name,
            lambda: McpToolCopyService().copy(source_b).name,
            lambda: McpToolCopyService().copy(source_c).name,
        ]
    )

    for outcome in outcomes:
        assert not isinstance(outcome, Exception), outcome
    assert len(set(outcomes)) == 3
    assert set(outcomes) == {"SharedMcp #4", "SharedMcp #5", "SharedMcp #6"}


# ---- (b) concurrent copies of the SAME source tool also still get unique
# names (the scenario the previous select_for_update-based fix targeted) ----


@pytest.mark.django_db(transaction=True)
def test_python_code_tool_concurrent_copies_of_same_source_get_unique_names():
    org = Organization.objects.create(name="Org PyToolSameSourceLock")
    source = _make_python_code_tool(org, name="ConcurrentTool")

    outcomes = _run_concurrently(
        [lambda: PythonCodeToolCopyService().copy(source).name for _ in range(5)]
    )

    for outcome in outcomes:
        assert not isinstance(outcome, Exception), outcome
    assert len(set(outcomes)) == 5
    assert set(outcomes) == {
        "ConcurrentTool #2",
        "ConcurrentTool #3",
        "ConcurrentTool #4",
        "ConcurrentTool #5",
        "ConcurrentTool #6",
    }


@pytest.mark.django_db(transaction=True)
def test_mcp_tool_concurrent_copies_of_same_source_get_unique_names():
    org = Organization.objects.create(name="Org McpSameSourceLock")
    source = _make_mcp_tool(org, name="ConcurrentMcp")

    outcomes = _run_concurrently(
        [lambda: McpToolCopyService().copy(source).name for _ in range(5)]
    )

    for outcome in outcomes:
        assert not isinstance(outcome, Exception), outcome
    assert len(set(outcomes)) == 5
    assert set(outcomes) == {
        "ConcurrentMcp #2",
        "ConcurrentMcp #3",
        "ConcurrentMcp #4",
        "ConcurrentMcp #5",
        "ConcurrentMcp #6",
    }


# ---- (c) fallback 400 path: a forced/unrelated collision still raises
# IntegrityError immediately (no retry to mask it), so mixins.py's existing
# except IntegrityError -> clean 400 handler still has something to catch ----


@pytest.mark.django_db
def test_python_code_tool_copy_still_raises_integrity_error_on_forced_collision(
    org, monkeypatch
):
    source = _make_python_code_tool(org, name="RaceTool")
    # Pre-create the row the (forced) generated candidate will collide with.
    _make_python_code_tool(org, name="RaceTool #2")

    monkeypatch.setattr(
        "tables.services.copy_services.python_code_tool_copy_service.ensure_unique_identifier",
        lambda base_name, existing_names: "RaceTool #2",
    )

    with pytest.raises(IntegrityError):
        PythonCodeToolCopyService().copy(source)


@pytest.mark.django_db
def test_mcp_tool_copy_still_raises_integrity_error_on_forced_collision(
    org, monkeypatch
):
    source = _make_mcp_tool(org, name="RaceMcp")
    _make_mcp_tool(org, name="RaceMcp #2")

    monkeypatch.setattr(
        "tables.services.copy_services.mcp_tool_copy_service.ensure_unique_identifier",
        lambda base_name, existing_names: "RaceMcp #2",
    )

    with pytest.raises(IntegrityError):
        McpToolCopyService().copy(source)
