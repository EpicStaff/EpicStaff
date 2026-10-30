"""GET /api/<resource>/recycle-bin/: limit/offset pages, search, ordering and the contents filter.

Filtering, sorting and counting happen before the page is cut, and only the active
org's rows are ever counted or listed.
"""

from datetime import timedelta

import pytest
from django.db import connection
from django.db.models import Model
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from agents.models import AgentDefinition, Surface
from rbac.models import Organization
from tables.models import Graph, KeyValueTable, KeyValueTableEntry, TaskNode
from tables.services.recycle_bin.presentation import bin_presentations
from tables.views.recycle_bin_mixins import RecycleBinPagination
from tests.api_tests.recycle_bin_cases import AGENTS_URL, CASES, FLOWS_URL, KEY_VALUE_TABLES_URL, BinCase
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("retention_seven_days")]

ENTRY_FIELDS = {"id", "name", "deleted_at", "days_left", "details", "contents", "hidden_contents", "contents_total"}


def _page(client, url: str, **params) -> dict:
    response = client.get(f"{url}recycle-bin/", params)
    assert response.status_code == 200, response.content
    return response.json()


def _ids(page: dict) -> list[int]:
    return [entry["id"] for entry in page["results"]]


def _binned(case: BinCase, org: Organization, names: list[str]) -> list[Model]:
    """Bin one row per name, an hour apart: the first name was deleted first."""
    rows = []
    for name in names:
        row = case.make(org, name)
        row.delete()
        rows.append(row)
    now = timezone.now()
    for hours_ago, row in enumerate(reversed(rows)):
        case.model.all_objects.filter(pk=row.pk).update(soft_deleted_at=now - timedelta(hours=hours_ago))
    return rows


@pytest.mark.parametrize("case", CASES, ids=[case.key for case in CASES])
class TestEveryBinPages:
    def test_sends_the_paging_envelope_with_the_orgs_count(self, case, acme_admin_client, acme, beta):
        ours = _binned(case, acme, [f"Ours {case.key} {index}" for index in range(3)])
        _binned(case, beta, [f"Theirs {case.key} {index}" for index in range(2)])

        page = _page(acme_admin_client, case.url)

        assert set(page) == {"count", "next", "previous", "results"}
        assert page["count"] == 3
        assert (page["next"], page["previous"]) == (None, None)
        assert _ids(page) == [row.pk for row in reversed(ours)]
        assert all(set(entry) == ENTRY_FIELDS for entry in page["results"])

    def test_limit_and_offset_page_through_the_bin(self, case, acme_admin_client, acme):
        rows = _binned(case, acme, [f"Paged {case.key} {index}" for index in range(3)])
        newest_first = [row.pk for row in reversed(rows)]

        first = _page(acme_admin_client, case.url, limit=2)
        second = acme_admin_client.get(first["next"]).json()
        by_offset = _page(acme_admin_client, case.url, limit=2, offset=2)

        assert (first["count"], second["count"]) == (3, 3)
        assert _ids(first) == newest_first[:2]
        assert _ids(second) == newest_first[2:]
        assert _ids(by_offset) == newest_first[2:]
        assert first["previous"] is None
        assert second["next"] is None
        assert second["previous"] is not None

    def test_limit_is_capped(self, case, acme_admin_client, acme, mocker):
        mocker.patch.object(RecycleBinPagination, "max_limit", 2)
        _binned(case, acme, [f"Capped {case.key} {index}" for index in range(3)])

        page = _page(acme_admin_client, case.url, limit=50)

        assert page["count"] == 3
        assert len(page["results"]) == 2

    def test_search_is_a_trimmed_case_insensitive_part_of_the_name(self, case, acme_admin_client, acme):
        report, upper_report, _other = _binned(
            case, acme, [f"alpha-report-{case.key}", f"beta-REPORT-{case.key}", f"gamma-{case.key}"]
        )

        page = _page(acme_admin_client, case.url, search="  Report ")

        assert page["count"] == 2
        assert _ids(page) == [upper_report.pk, report.pk]
        assert _page(acme_admin_client, case.url, search="   ")["count"] == 3
        assert _page(acme_admin_client, case.url, search="no-such-name")["count"] == 0

    @pytest.mark.parametrize(
        "ordering, oldest_first",
        [
            ("-deleted_at", False),
            ("deleted_at", True),
            # Days left: the oldest deletion has the fewest left.
            ("days_left", True),
            ("-days_left", False),
            ("not-an-ordering", False),
            ("", False),
        ],
    )
    def test_ordering(self, case, acme_admin_client, acme, ordering, oldest_first):
        rows = _binned(case, acme, [f"Sorted {case.key} {index}" for index in range(3)])
        oldest_to_newest = [row.pk for row in rows]

        page = _page(acme_admin_client, case.url, ordering=ordering)

        assert _ids(page) == (oldest_to_newest if oldest_first else oldest_to_newest[::-1])

    def test_rows_deleted_at_the_same_time_are_ordered_by_id(self, case, acme_admin_client, acme):
        rows = _binned(case, acme, [f"Tied {case.key} {index}" for index in range(3)])
        case.model.all_objects.filter(pk__in=[row.pk for row in rows]).update(soft_deleted_at=timezone.now())
        ids = sorted(row.pk for row in rows)

        assert _ids(_page(acme_admin_client, case.url, ordering="-deleted_at")) == ids[::-1]
        assert _ids(_page(acme_admin_client, case.url, ordering="deleted_at")) == ids
        pages = [_ids(_page(acme_admin_client, case.url, ordering="days_left", limit=1, offset=offset)) for offset in range(3)]
        assert pages == [[pk] for pk in ids]

    def test_a_row_with_nothing_inside_counts_as_none(self, case, acme_admin_client, acme, beta):
        row = _binned(case, acme, [f"Empty {case.key}"])[0]
        _binned(case, beta, [f"Theirs empty {case.key}"])

        assert _ids(_page(acme_admin_client, case.url, contents="none")) == [row.pk]
        assert _page(acme_admin_client, case.url, contents="some")["count"] == 0
        assert _page(acme_admin_client, case.url, contents="anything")["count"] == 1
        assert _page(acme_admin_client, case.url, contents="")["count"] == 1

    def test_paging_never_counts_or_lists_another_orgs_rows(self, case, acme_admin_client, acme, beta):
        ours = _binned(case, acme, [f"Shared word ours {case.key} {index}" for index in range(2)])
        theirs = _binned(case, beta, [f"Shared word theirs {case.key} {index}" for index in range(3)])
        their_ids = {row.pk for row in theirs}

        pages = [_page(acme_admin_client, case.url, limit=1, offset=offset, search="shared word") for offset in range(5)]

        assert {page["count"] for page in pages} == {2}
        listed = [pk for page in pages for pk in _ids(page)]
        assert listed == [row.pk for row in reversed(ours)]
        assert not their_ids & set(listed)
        assert _page(acme_admin_client, case.url, contents="none", search="theirs")["count"] == 0


def test_the_default_page_is_50_and_no_page_is_over_100(acme_admin_client, acme):
    Graph.objects.bulk_create([Graph(org=acme, name=f"Many {index}") for index in range(101)])
    for graph in Graph.objects.filter(org=acme, name__startswith="Many "):
        graph.delete()

    default = _page(acme_admin_client, FLOWS_URL)
    largest = _page(acme_admin_client, FLOWS_URL, limit=500)

    assert (default["count"], len(default["results"])) == (101, 50)
    assert (largest["count"], len(largest["results"])) == (101, 100)
    assert largest["next"] is not None


def _flow_with_tasks(org: Organization, name: str, tasks: int) -> Graph:
    graph = Graph.objects.create(org=org, name=name)
    TaskNode.objects.bulk_create([TaskNode(graph=graph, node_name=f"{name} task {index}") for index in range(tasks)])
    graph.delete()
    return graph


@pytest.mark.parametrize("case", CASES, ids=[case.key for case in CASES])
def test_the_contents_filter_matches_contents_total(case, acme_admin_client, acme):
    if not bin_presentations()[case.key].content_sources:
        pytest.skip(f"A {case.key} has nothing inside: its restore brings back only itself")
    assert case.add_contents is not None, f"{case.key} has contents: give its BinCase add_contents"
    full = case.make(acme, f"Full {case.key}")
    case.add_contents(full)
    empty = case.make(acme, f"Empty {case.key}")
    for row in (full, empty):
        response = acme_admin_client.delete(f"{case.url}{row.pk}/")
        assert response.status_code == case.delete_status, response.content

    listed = _page(acme_admin_client, case.url)["results"]
    some = _ids(_page(acme_admin_client, case.url, contents="some"))
    none = _ids(_page(acme_admin_client, case.url, contents="none"))

    assert some == [entry["id"] for entry in listed if entry["contents_total"] > 0]
    assert none == [entry["id"] for entry in listed if entry["contents_total"] == 0]
    # Each side holds a row, so the parity above can't pass on two empty lists.
    assert (some, none) == ([full.pk], [empty.pk])


class TestContentsFilter:
    def test_flows_with_nodes_are_some_and_empty_flows_none(self, acme_admin_client, acme, beta):
        with_nodes = _flow_with_tasks(acme, "With nodes", tasks=2)
        empty = _flow_with_tasks(acme, "Empty", tasks=0)
        _flow_with_tasks(beta, "Theirs with nodes", tasks=1)

        some = _page(acme_admin_client, FLOWS_URL, contents="some")
        none = _page(acme_admin_client, FLOWS_URL, contents="none")

        assert (some["count"], _ids(some)) == (1, [with_nodes.pk])
        assert some["results"][0]["contents_total"] == 2
        assert (none["count"], _ids(none)) == (1, [empty.pk])
        assert none["results"][0]["contents_total"] == 0

    def test_counts_only_what_the_restore_brings_back(self, acme_admin_client, acme):
        agent = AgentDefinition.objects.create(org=acme, name="Owner", instruction_list=[])
        Surface.objects.create(org=acme, name="Deleted before", owner_agent=agent).delete()
        acme_admin_client.delete(f"{AGENTS_URL}{agent.pk}/")
        with_surface = AgentDefinition.objects.create(org=acme, name="With surface", instruction_list=[])
        Surface.objects.create(org=acme, name="Comes back", owner_agent=with_surface)
        acme_admin_client.delete(f"{AGENTS_URL}{with_surface.pk}/")

        assert _ids(_page(acme_admin_client, AGENTS_URL, contents="some")) == [with_surface.pk]
        assert _ids(_page(acme_admin_client, AGENTS_URL, contents="none")) == [agent.pk]

    def test_a_table_counts_its_keys_without_naming_them(self, acme_admin_client, acme):
        table = KeyValueTable.objects.create(org=acme, name="Keys")
        KeyValueTableEntry.objects.create(table=table, key="private", value="x")
        acme_admin_client.delete(f"{KEY_VALUE_TABLES_URL}{table.pk}/")

        entry = _page(acme_admin_client, KEY_VALUE_TABLES_URL, contents="some")["results"][0]

        assert (entry["id"], entry["contents"], entry["contents_total"]) == (table.pk, [], 1)

    def test_pages_the_filtered_rows(self, acme_admin_client, acme):
        flows = [_flow_with_tasks(acme, f"Full {index}", tasks=1) for index in range(3)]
        _flow_with_tasks(acme, "Empty", tasks=0)

        first = _page(acme_admin_client, FLOWS_URL, contents="some", limit=2)
        second = acme_admin_client.get(first["next"]).json()

        assert (first["count"], len(first["results"]), len(second["results"])) == (3, 2, 1)
        assert set(_ids(first) + _ids(second)) == {flow.pk for flow in flows}

    def test_query_count_does_not_grow_with_the_bin(self, acme_admin_client, acme):
        _flow_with_tasks(acme, "First", tasks=1)
        with CaptureQueriesContext(connection) as small_bin:
            _page(acme_admin_client, FLOWS_URL, contents="some", limit=1)
        for index in range(4):
            _flow_with_tasks(acme, f"More {index}", tasks=2)
        with CaptureQueriesContext(connection) as big_bin:
            page = _page(acme_admin_client, FLOWS_URL, contents="some", limit=1)

        assert page["count"] == 5
        assert len(big_bin) == len(small_bin)
