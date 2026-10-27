"""The storage endpoints over the real StorageManager; only the object store is
replaced, by the in-memory backend (contract-tested in test_storage_backend_contract.py)."""

import io
import zipfile
from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from rbac.models import Organization, OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.models import Graph, GraphStorageFile, StorageFile
from tables.services.storage_service.db_sync import StorageFileSync
from tables.services.storage_service.manager import StorageManager
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend
from tests.storage_tests.storage_writes import store_object

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def store():
    backend = InMemoryStorageBackend(organization_prefix="")
    with patch("tables.views.storage_views.get_storage_manager", return_value=StorageManager(backend)):
        yield backend


@pytest.fixture
def put(store, default_org):
    def _put(path, data=b"x", org=None):
        store_object(store, (org or default_org).id, path, data)

    return _put


def _exists(store, org, path):
    return store.exists(f"org_{org.id}/{path}")


def _body(resp) -> bytes:
    return b"".join(resp.streaming_content) if resp.streaming else resp.content


def test_list_returns_the_folders_files(auth_client, put):
    put("a.txt", b"0123456789")
    put("docs/inner.txt")

    resp = auth_client.get("/api/storage/list/", {"path": ""})

    assert resp.status_code == status.HTTP_200_OK
    assert {(item["name"], item["type"]) for item in resp.data["items"]} == {("a.txt", "file"), ("docs", "folder")}
    assert next(item["size"] for item in resp.data["items"] if item["name"] == "a.txt") == 10


@pytest.mark.parametrize(("path", "expected_status"), [("f.txt", 200), ("ghost.txt", 404)])
def test_info(auth_client, put, path, expected_status):
    put("f.txt", b"hello")

    resp = auth_client.get("/api/storage/info/", {"path": path})

    assert resp.status_code == expected_status
    if expected_status == 200:
        assert (resp.data["name"], resp.data["size"], resp.data["graphs"]) == ("f.txt", 5, [])


@pytest.fixture
def make_files_reader_client(default_org, django_user_model):
    """Factory for an API client of a default-org member whose custom role reads files.

    The role also grants whatever `other_permissions` maps resource types to.
    """

    def _make(other_permissions: dict[ResourceType, Permission]):
        role = Role.objects.create(name="Files reader", org=default_org, is_built_in=False)
        for resource_type, permissions in {ResourceType.FILES: Permission.READ, **other_permissions}.items():
            RolePermission.objects.create(role=role, resource_type=resource_type.value, permissions=int(permissions))
        user = django_user_model.objects.create_user(email="files-reader@example.com", password="StrongPass123!")
        OrganizationUser.objects.create(user=user, org=default_org, role=role)
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
        return client

    return _make


@pytest.mark.parametrize(
    ("other_permissions", "expect_graphs"),
    [({ResourceType.FLOWS: Permission.READ}, True), ({}, False)],
    ids=["with-flows-read", "without-flows-read"],
)
def test_info_lists_the_flows_using_the_file_only_for_a_caller_who_can_read_flows(
    auth_client, make_files_reader_client, put, default_org, other_permissions, expect_graphs
):
    put("f.txt", b"hello")
    graph = Graph.objects.create(name="secret-flow", org=default_org)
    linked = auth_client.post(
        "/api/storage/add-to-graph/", {"paths": ["f.txt"], "graph_ids": [graph.id]}, format="json"
    )
    assert linked.status_code == status.HTTP_201_CREATED

    resp = make_files_reader_client(other_permissions).get("/api/storage/info/", {"path": "f.txt"})

    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["graphs"] == ([{"id": graph.id, "name": "secret-flow"}] if expect_graphs else [])


@pytest.mark.parametrize(
    ("path", "range_header", "expected_status", "expected_body", "content_range"),
    [
        ("f.txt", None, 200, b"file content", None),
        ("f.txt", "bytes=0-3", 206, b"file", "bytes 0-3/12"),
        ("f.txt", "bytes=99-", 416, None, "bytes */12"),
        ("ghost.txt", None, 404, None, None),
    ],
    ids=["whole", "range", "range-past-end", "missing"],
)
def test_download(auth_client, put, path, range_header, expected_status, expected_body, content_range):
    put("f.txt", b"file content")
    headers = {"HTTP_RANGE": range_header} if range_header else {}

    resp = auth_client.get("/api/storage/download/", {"path": path}, **headers)

    assert resp.status_code == expected_status
    if expected_body is not None:
        assert _body(resp) == expected_body
        assert resp["Accept-Ranges"] == "bytes"
    if content_range is not None:
        assert resp["Content-Range"] == content_range


def test_download_zip_packs_the_folder(auth_client, put):
    put("folder/a.txt", b"A")
    put("folder/sub/b.txt", b"B")

    resp = auth_client.post("/api/storage/download-zip/", {"paths": ["folder"]}, format="json")

    assert resp.status_code == status.HTTP_200_OK
    assert resp["Content-Disposition"] == 'attachment; filename="folder.zip"'
    archive = zipfile.ZipFile(io.BytesIO(_body(resp)))
    files = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
    assert sorted(files.values()) == [b"A", b"B"]


@pytest.mark.parametrize(
    ("url", "body"),
    [
        ("/api/storage/download-zip/", {"paths": ["ghost"]}),
        ("/api/storage/rename/", {"from_path": "ghost.txt", "to_path": "new.txt"}),
    ],
    ids=["download-zip", "rename"],
)
def test_a_missing_source_is_a_400(auth_client, url, body):
    assert auth_client.post(url, body, format="json").status_code == status.HTTP_400_BAD_REQUEST


def test_rename_moves_the_file(auth_client, put, store, default_org):
    put("old.txt")

    resp = auth_client.post("/api/storage/rename/", {"from_path": "old.txt", "to_path": "new.txt"}, format="json")

    assert resp.status_code == status.HTTP_200_OK
    assert (_exists(store, default_org, "old.txt"), _exists(store, default_org, "new.txt")) == (False, True)


@pytest.mark.parametrize(("action", "source_kept"), [("move", False), ("copy", True)])
def test_move_and_copy_within_the_org(auth_client, put, store, default_org, action, source_kept):
    put("a.txt")
    auth_client.post("/api/storage/mkdir/", {"path": "dest"}, format="json")

    resp = auth_client.post(f"/api/storage/{action}/", {"from_path": "a.txt", "to_path": "dest"}, format="json")

    assert resp.status_code == status.HTTP_200_OK
    assert _exists(store, default_org, "dest/a.txt")
    assert _exists(store, default_org, "a.txt") is source_kept


@pytest.mark.parametrize(("action", "source_kept"), [("move", False), ("copy", True)])
def test_move_and_copy_across_orgs_for_a_superadmin(
    superadmin_client_with_org, put, store, default_org, action, source_kept
):
    other_org = Organization.objects.create(name="other-org")
    put("a.txt", b"payload")

    resp = superadmin_client_with_org.post(
        f"/api/storage/{action}/",
        {"from_path": "a.txt", "to_path": "inbox", "source_org_id": default_org.id, "destination_org_id": other_org.id},
        format="json",
    )

    assert resp.status_code == status.HTTP_200_OK
    assert [store.download(key) for key in store.list_all_keys(f"org_{other_org.id}")] == [b"payload"]
    assert _exists(store, default_org, "a.txt") is source_kept


@pytest.mark.parametrize("action", ["move", "copy"])
@pytest.mark.parametrize(
    ("org_ids", "rejected_field"),
    [
        ({"source_org_id": "active"}, "destination_org_id"),
        ({"destination_org_id": "other"}, "source_org_id"),
        ({"source_org_id": "other", "destination_org_id": None}, "destination_org_id"),
        ({"source_org_id": "active", "destination_org_id": "active"}, "destination_org_id"),
        ({"source_org_id": "other", "destination_org_id": "other"}, "destination_org_id"),
        ({"source_org_id": 0, "destination_org_id": "other"}, "source_org_id"),
    ],
    ids=["only-source", "only-destination", "destination-null", "same-active-org", "same-other-org", "org-id-zero"],
)
def test_a_transfer_naming_not_two_different_orgs_is_a_400_and_touches_nothing(
    superadmin_client_with_org, put, store, default_org, action, org_ids, rejected_field
):
    other_org = Organization.objects.create(name="other-org")
    orgs = {"active": default_org.id, "other": other_org.id}
    put("a.txt")
    put("a.txt", org=other_org)

    resp = superadmin_client_with_org.post(
        f"/api/storage/{action}/",
        {"from_path": "a.txt", "to_path": "moved.txt", **{key: orgs.get(value, value) for key, value in org_ids.items()}},
        format="json",
    )

    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.data["message"].startswith(f"{rejected_field}: ")
    for org in (default_org, other_org):
        assert (_exists(store, org, "a.txt"), _exists(store, org, "moved.txt")) == (True, False)


def test_delete_removes_the_files(auth_client, put, store, default_org):
    put("a.txt")

    resp = auth_client.delete("/api/storage/delete/", {"paths": ["a.txt"]}, format="json")

    assert resp.status_code == status.HTTP_204_NO_CONTENT
    assert not _exists(store, default_org, "a.txt")
    assert not StorageFile.objects.filter(org=default_org, path="a.txt").exists()


def test_mkdir_creates_the_folder(auth_client, store, default_org):
    resp = auth_client.post("/api/storage/mkdir/", {"path": "new_folder"}, format="json")

    assert resp.status_code == status.HTTP_201_CREATED
    assert _exists(store, default_org, "new_folder/")


def test_graph_links_are_added_listed_and_removed(auth_client, put, default_org):
    graph = Graph.objects.create(name="test-graph", org=default_org)
    put("docs/a.txt")

    added = auth_client.post("/api/storage/add-to-graph/", {"paths": ["docs"], "graph_ids": [graph.id]}, format="json")
    listed = auth_client.get("/api/storage/graph-files/", {"graph_id": graph.id})
    removed = auth_client.delete(
        "/api/storage/remove-from-graph/", {"paths": ["docs/"], "graph_ids": [graph.id]}, format="json"
    )

    assert added.status_code == status.HTTP_201_CREATED
    # A folder is linked by its folder path, with the trailing slash.
    assert listed.status_code == status.HTTP_200_OK
    assert [item["path"] for item in listed.data] == ["docs/"]
    assert removed.status_code == status.HTTP_204_NO_CONTENT
    assert not GraphStorageFile.objects.filter(graph=graph).exists()


class TestTree:
    def test_tree_returns_the_nested_folder(self, auth_client, put):
        put("reports/q1.pdf", b"x" * 10)
        put("reports/2025/summary.txt")

        resp = auth_client.get("/api/storage/tree/", {"path": "reports"})

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["truncated"] is False
        tree = resp.data["tree"]
        assert tree["name"] == "reports"
        assert [(child["name"], child["children"] is None) for child in tree["children"]] == [
            ("2025", False),
            ("q1.pdf", True),
        ]

    def test_tree_stops_at_max_depth(self, auth_client, put):
        put("a/b/c/d.txt")

        resp = auth_client.get("/api/storage/tree/", {"path": "a", "max_depth": 1})

        (b,) = resp.data["tree"]["children"]
        assert (b["name"], b["children"]) == ("b", [])

    @pytest.mark.parametrize(("path", "expected_status"), [("nope", 404), ("f.txt", 400)], ids=["missing", "a-file"])
    def test_tree_needs_an_existing_folder(self, auth_client, put, path, expected_status):
        put("f.txt")

        assert auth_client.get("/api/storage/tree/", {"path": path}).status_code == expected_status


class TestFilesByIds:
    def test_returns_this_orgs_files_and_omits_missing_or_foreign_ids(self, auth_client, default_org):
        own = StorageFile.objects.create(org=default_org, path="reports/q1.pdf", name="q1.pdf", size=100)
        other_org = Organization.objects.create(name="other-org")
        foreign = StorageFile.objects.create(org=other_org, path="foreign.txt", name="foreign.txt")

        resp = auth_client.get("/api/storage/files/", {"ids": f"{own.id},{foreign.id},999999"})

        assert resp.status_code == status.HTTP_200_OK
        assert [(item["id"], item["path"], item["name"], item["size"]) for item in resp.data] == [
            (own.id, "reports/q1.pdf", "q1.pdf", 100)
        ]

    @pytest.mark.parametrize("ids", ["1,abc", ""], ids=["non-numeric", "empty"])
    def test_rejects_bad_ids(self, auth_client, ids):
        assert auth_client.get("/api/storage/files/", {"ids": ids}).status_code == status.HTTP_400_BAD_REQUEST


class TestSearch:
    def test_search_pages_case_insensitive_matches_under_the_path(self, auth_client, put):
        for name in ("reports/q1_report.pdf", "reports/q2_report.pdf", "archive/old_report.txt", "notes.txt"):
            put(name)

        resp = auth_client.get("/api/storage/search/", {"q": "REPORT", "path": "reports/", "limit": 1, "offset": 1})

        assert resp.status_code == status.HTTP_200_OK
        assert (resp.data["total"], resp.data["offset"], resp.data["limit"]) == (2, 1, 1)
        assert len(resp.data["results"]) == 1
        assert resp.data["results"][0]["path"].startswith("reports/")

    @pytest.mark.parametrize(
        "params", [{"q": "r"}, {}, {"q": "rep", "limit": 999}], ids=["short-query", "no-query", "limit-over-max"]
    )
    def test_search_rejects_bad_parameters(self, auth_client, params):
        assert auth_client.get("/api/storage/search/", params).status_code == status.HTTP_400_BAD_REQUEST


def test_a_file_recorded_by_a_sandbox_mutation_is_listed(auth_client, default_org):
    """The sandbox's storage-mutation handler records files through StorageFileSync.on_upload."""
    StorageFileSync.on_upload(default_org.id, "gen/out.txt")

    resp = auth_client.get("/api/storage/list/", {"path": "gen"})

    assert resp.status_code == status.HTTP_200_OK
    assert [item["name"] for item in resp.data["items"]] == ["out.txt"]
