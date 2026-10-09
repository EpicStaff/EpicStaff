"""The storage recycle bin: list, restore (with parent folders and renames) and purge."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.exceptions import NotInRecycleBinError, StorageRestoreConflictError
from tables.models import StorageFile
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.recycle_bin import StorageRecycleBinService
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file

pytestmark = pytest.mark.django_db

BIN = "/api/storage/recycle-bin/"


@pytest.fixture(autouse=True)
def retention_seven_days(settings):
    settings.RECYCLE_BIN_RETENTION_DAYS = 7


@pytest.fixture
def manager():
    return StorageManager(InMemoryStorageBackend(organization_prefix=""))


@pytest.fixture
def service(manager):
    return StorageRecycleBinService(manager)


def _objects(manager) -> dict:
    return manager._backend._objects


def _row(org, path) -> StorageFile:
    return StorageFile.all_objects.filter(org=org, path=path).order_by("-pk").first()


def _trash_keys(manager, org, batch) -> list[str]:
    return [key for key in _objects(manager) if key.startswith(f"org_{org.id}/.recycle-bin/{batch}/")]


class TestRestore:
    def test_a_file_deleted_with_its_folder_comes_back_only_with_it(self, manager, service, org):
        seed_file(manager._backend, org.id, "docs/a.txt", b"a")
        batch = manager.delete(org.id, "docs")

        with pytest.raises(NotInRecycleBinError):
            service.restore(org.id, _row(org, "docs/a.txt").pk)

        assert _row(org, "docs/a.txt").active is False
        assert _row(org, "docs/").active is False
        assert _trash_keys(manager, org, batch) != []

    def test_a_folder_comes_back_whole(self, manager, service, org):
        manager.mkdir(org.id, "docs")
        seed_file(manager._backend, org.id, "docs/a.txt", b"a")
        seed_file(manager._backend, org.id, "docs/sub/b.txt", b"b")
        batch = manager.delete(org.id, "docs")

        service.restore(org.id, _row(org, "docs/").pk)

        assert set(StorageFile.objects.filter(org=org).values_list("path", flat=True)) == {
            "docs/",
            "docs/a.txt",
            "docs/sub/",
            "docs/sub/b.txt",
        }
        assert _objects(manager)[f"org_{org.id}/docs/sub/b.txt"][0] == b"b"
        assert _trash_keys(manager, org, batch) == []

    def test_a_folder_whose_name_is_taken_comes_back_renamed_with_its_contents(self, manager, service, org):
        seed_file(manager._backend, org.id, "docs/a.txt", b"old")
        manager.delete(org.id, "docs")
        manager.mkdir(org.id, "docs")

        result = service.restore(org.id, StorageFile.deleted_objects.get(org=org, path="docs/").pk)

        assert result.renamed_from == "docs/"
        assert result.object.path == "docs #2/"
        child = StorageFile.objects.get(org=org, path="docs #2/a.txt")
        assert child.parent_path == "docs #2/"
        assert _objects(manager)[f"org_{org.id}/docs #2/a.txt"][0] == b"old"

    def test_a_file_whose_name_is_taken_comes_back_renamed(self, manager, service, org):
        seed_file(manager._backend, org.id, "report.pdf", b"v1")
        manager.delete(org.id, "report.pdf")
        seed_file(manager._backend, org.id, "report.pdf", b"v2")

        result = service.restore(org.id, StorageFile.deleted_objects.get(org=org, path="report.pdf").pk)

        assert result.object.path == "report #2.pdf"
        assert _objects(manager)[f"org_{org.id}/report #2.pdf"][0] == b"v1"
        assert _objects(manager)[f"org_{org.id}/report.pdf"][0] == b"v2"

    def test_a_parent_deleted_on_its_own_stays_whole_in_the_bin(self, manager, service, org):
        seed_file(manager._backend, org.id, "docs/a.txt", b"a")
        seed_file(manager._backend, org.id, "docs/b.txt", b"b")
        manager.delete(org.id, "docs/a.txt")
        manager.delete(org.id, "docs")
        deleted_folder = StorageFile.deleted_objects.get(org=org, path="docs/")

        service.restore(org.id, StorageFile.deleted_objects.get(org=org, path="docs/a.txt").pk)

        assert StorageFile.objects.filter(org=org, path="docs/").exclude(pk=deleted_folder.pk).exists()
        assert StorageFile.deleted_objects.filter(pk=deleted_folder.pk).exists()
        assert _row(org, "docs/b.txt").active is False
        assert _objects(manager)[f"org_{org.id}/docs/a.txt"][0] == b"a"

    def test_a_parent_that_no_longer_exists_is_created(self, manager, service, org):
        seed_file(manager._backend, org.id, "docs/a.txt", b"a")
        manager.delete(org.id, "docs/a.txt")
        StorageFile.objects.filter(org=org, path="docs/").delete()

        service.restore(org.id, _row(org, "docs/a.txt").pk)

        assert StorageFile.objects.filter(org=org, path="docs/", item_type="folder").exists()

    def test_an_unindexed_object_at_the_target_is_a_conflict(self, manager, service, org):
        seed_file(manager._backend, org.id, "report.pdf", b"v1")
        manager.delete(org.id, "report.pdf")
        manager._backend.put_bytes(f"org_{org.id}/report.pdf", b"stray")

        with pytest.raises(StorageRestoreConflictError):
            service.restore(org.id, _row(org, "report.pdf").pk)

        assert _row(org, "report.pdf").active is False

    def test_a_live_row_is_not_in_the_bin(self, manager, service, org):
        seed_file(manager._backend, org.id, "a.txt", b"a")

        with pytest.raises(NotInRecycleBinError):
            service.restore(org.id, _row(org, "a.txt").pk)


class TestPurge:
    def test_a_file_goes_for_good(self, manager, service, org):
        seed_file(manager._backend, org.id, "a.txt", b"a")
        batch = manager.delete(org.id, "a.txt")
        row = _row(org, "a.txt")

        service.purge(org.id, row.pk, actor="test")

        assert not StorageFile.all_objects.filter(pk=row.pk).exists()
        assert _trash_keys(manager, org, batch) == []

    def test_a_folder_goes_with_its_batch(self, manager, service, org):
        seed_file(manager._backend, org.id, "docs/a.txt", b"a")
        seed_file(manager._backend, org.id, "docs/sub/b.txt", b"b")
        batch = manager.delete(org.id, "docs")

        service.purge(org.id, _row(org, "docs/").pk, actor="test")

        assert not StorageFile.all_objects.filter(org=org, path__startswith="docs/").exists()
        assert _trash_keys(manager, org, batch) == []

    def test_a_file_deleted_with_its_folder_goes_only_with_it(self, manager, service, org):
        seed_file(manager._backend, org.id, "docs/a.txt", b"a")
        batch = manager.delete(org.id, "docs")

        with pytest.raises(NotInRecycleBinError):
            service.purge(org.id, _row(org, "docs/a.txt").pk, actor="test")

        assert f"org_{org.id}/.recycle-bin/{batch}/docs/a.txt" in _objects(manager)

    def test_purge_frees_quota(self, manager, service, org):
        from tables.services.storage_service.quota import org_used_bytes

        seed_file(manager._backend, org.id, "a.txt", b"abcde")
        manager.delete(org.id, "a.txt")

        service.purge(org.id, _row(org, "a.txt").pk, actor="test")

        assert org_used_bytes(org.id) == 0

    def test_an_expired_batch_purges_only_after_its_cutoff(self, manager, service, org):
        seed_file(manager._backend, org.id, "a.txt", b"a")
        batch = manager.delete(org.id, "a.txt")
        deleted_at = _row(org, "a.txt").soft_deleted_at

        assert service.purge_expired_batch(org.id, batch, deleted_at - timedelta(seconds=1), actor="test") == 0
        assert service.purge_expired_batch(org.id, batch, deleted_at + timedelta(seconds=1), actor="test") == 1
        assert not StorageFile.all_objects.filter(org=org, path="a.txt").exists()


@pytest.fixture
def real_manager():
    storage_manager = StorageManager(InMemoryStorageBackend(organization_prefix=""))
    with patch("tables.views.storage_views.get_storage_manager", return_value=storage_manager):
        yield storage_manager


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def client_with_files_bits(client_as, django_user_model, acme):
    def _make(bits: Permission) -> APIClient:
        role = Role.objects.create(name=f"Files {int(bits)}", org=acme, is_built_in=False)
        RolePermission.objects.create(role=role, resource_type=ResourceType.FILES.value, permissions=int(bits))
        user = django_user_model.objects.create_user(email=f"files-{int(bits)}@example.com", password="StrongPass123!")
        OrganizationUser.objects.create(user=user, org=acme, role=role)
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
        return client

    return _make


def _binned(manager, org, path, content=b"x") -> StorageFile:
    seed_file(manager._backend, org.id, path, content)
    manager.delete(org.id, path)
    return StorageFile.deleted_objects.get(org=org, path=path)


class TestStorageBinApi:
    def test_list_shows_binned_rows_newest_first(self, admin_client, real_manager, acme, beta):
        older = _binned(real_manager, acme, "old.txt")
        StorageFile.all_objects.filter(pk=older.pk).update(soft_deleted_at=timezone.now() - timedelta(hours=1))
        seed_file(real_manager._backend, acme.id, "docs/a.txt", b"a")
        real_manager.delete(acme.id, "docs")
        seed_file(real_manager._backend, acme.id, "live.txt", b"l")
        _binned(real_manager, beta, "theirs.txt")

        page = admin_client.get(BIN).json()
        entries = page["results"]

        assert page["count"] == 2  # docs/a.txt goes with its folder, so it isn't listed
        assert set(entries[0]) == {
            "id",
            "name",
            "item_type",
            "deleted_at",
            "days_left",
            "details",
            "contents",
            "contents_total",
        }
        folder_details = {detail["label"]: detail["value"] for detail in entries[0]["details"]}
        file_details = {detail["label"]: detail["value"] for detail in entries[1]["details"]}
        assert list(folder_details) == ["Location", "Created", "Last changed"]
        assert folder_details["Location"] == "/"
        assert list(file_details) == ["Location", "Size", "Type", "Created", "Last changed"]
        assert (file_details["Location"], file_details["Size"], file_details["Type"]) == ("/", 1, "TXT")
        assert entries[0]["contents"] == [{"name": "a.txt", "kind": "file"}]
        assert entries[0]["contents_total"] == 1
        assert (entries[1]["contents"], entries[1]["contents_total"]) == ([], 0)
        assert [entry["name"] for entry in entries] == ["docs/", "old.txt"]
        assert entries[0]["item_type"] == "folder"
        assert entries[0]["days_left"] == 7

    def test_a_file_whose_folder_is_gone_warns_it_comes_back_in_a_new_one(
        self, admin_client, real_manager, acme
    ):
        _binned(real_manager, acme, "docs/a.txt")
        _binned(real_manager, acme, "keep/b.txt")
        real_manager.delete(acme.id, "docs")

        entries = {entry["name"]: entry for entry in admin_client.get(BIN).json()["results"]}

        orphan = {detail["label"]: detail for detail in entries["docs/a.txt"]["details"]}
        assert orphan["Comes back to"]["format"] == "notice"
        assert "docs/" in orphan["Comes back to"]["value"]
        kept = {detail["label"] for detail in entries["keep/b.txt"]["details"]}
        assert "Comes back to" not in kept  # keep/ is live

    def test_list_is_paged(self, admin_client, real_manager, acme):
        for index in range(3):
            _binned(real_manager, acme, f"f{index}.txt")

        first = admin_client.get(BIN, {"limit": 2}).json()
        second = admin_client.get(first["next"]).json()

        assert first["count"] == 3
        assert len(first["results"]) == 2
        assert len(second["results"]) == 1
        assert {entry["id"] for entry in first["results"] + second["results"]} == set(
            StorageFile.deleted_objects.filter(org=acme).values_list("pk", flat=True)
        )

    def test_restore_returns_each_id_with_its_path(self, admin_client, real_manager, acme):
        seed_file(real_manager._backend, acme.id, "docs/a.txt", b"a")
        real_manager.delete(acme.id, "docs")
        folder = _row(acme, "docs/")
        loose = _binned(real_manager, acme, "notes.txt")

        response = admin_client.post(f"{BIN}restore/", {"ids": [folder.pk, loose.pk]}, format="json")

        assert response.status_code == 200, response.content
        assert response.json() == {
            "restored": [
                {"id": folder.pk, "name": "docs/", "renamed_from": None},
                {"id": loose.pk, "name": "notes.txt", "renamed_from": None},
            ],
            "failed": [],
        }
        assert _row(acme, "docs/a.txt").active is True

    @pytest.mark.parametrize("action", ["restore", "purge"])
    def test_an_id_deleted_with_its_folder_is_404(self, admin_client, real_manager, acme, action):
        seed_file(real_manager._backend, acme.id, "docs/a.txt", b"a")
        real_manager.delete(acme.id, "docs")

        response = admin_client.post(
            f"{BIN}{action}/", {"ids": [_row(acme, "docs/a.txt").pk]}, format="json"
        )

        assert response.status_code == 404
        assert response.json()["code"] == "not_in_recycle_bin"
        assert StorageFile.deleted_objects.filter(org=acme, path__startswith="docs/").count() == 2

    def test_a_restore_conflict_is_reported_and_the_rest_go_on(self, admin_client, real_manager, acme):
        blocked = _binned(real_manager, acme, "report.pdf")
        fine = _binned(real_manager, acme, "notes.txt")
        real_manager._backend.put_bytes(f"org_{acme.id}/report.pdf", b"stray")

        response = admin_client.post(f"{BIN}restore/", {"ids": [blocked.pk, fine.pk]}, format="json")

        assert response.status_code == 200, response.content
        body = response.json()
        assert [item["id"] for item in body["restored"]] == [fine.pk]
        assert [(item["id"], item["name"]) for item in body["failed"]] == [(blocked.pk, "report.pdf")]
        assert "storage already holds a file" in body["failed"][0]["message"]

    def test_an_id_outside_the_bin_says_so_in_its_code(self, admin_client, real_manager, acme, beta):
        theirs = _binned(real_manager, beta, "theirs.txt")

        response = admin_client.post(f"{BIN}restore/", {"ids": [theirs.pk]}, format="json")

        assert response.status_code == 404
        assert response.json()["code"] == "not_in_recycle_bin"

    def test_purge(self, admin_client, real_manager, acme):
        row = _binned(real_manager, acme, "a.txt")

        response = admin_client.post(f"{BIN}purge/", {"ids": [row.pk]}, format="json")

        assert response.status_code == 200, response.content
        assert response.json() == {"purged": [row.pk], "failed": []}
        assert not StorageFile.all_objects.filter(pk=row.pk).exists()

    def test_all_empties_the_bin(self, admin_client, real_manager, acme, beta):
        ours = [_binned(real_manager, acme, name) for name in ("a.txt", "b.txt")]
        theirs = _binned(real_manager, beta, "theirs.txt")

        response = admin_client.post(f"{BIN}purge/", {"all": True}, format="json")

        assert response.status_code == 200, response.content
        assert sorted(response.json()["purged"]) == sorted(row.pk for row in ours)
        assert StorageFile.deleted_objects.filter(pk=theirs.pk).exists()

    def test_all_restores_the_bin(self, admin_client, real_manager, acme):
        rows = [_binned(real_manager, acme, name) for name in ("a.txt", "b.txt")]

        response = admin_client.post(f"{BIN}restore/", {"all": True}, format="json")

        assert response.status_code == 200, response.content
        assert StorageFile.objects.filter(pk__in=[row.pk for row in rows]).count() == 2

    @pytest.mark.parametrize("body", [{}, {"all": True, "ids": [1]}, {"all": False}])
    def test_either_ids_or_all(self, admin_client, real_manager, body):
        assert admin_client.post(f"{BIN}restore/", body, format="json").status_code == 400

    def test_search_and_ordering(self, admin_client, real_manager, acme):
        for name in ("beta.txt", "alpha.txt", "gamma.md"):
            _binned(real_manager, acme, name)

        oldest_first = admin_client.get(BIN, {"ordering": "deleted_at"}).json()["results"]
        found = admin_client.get(BIN, {"search": "ALPHA"}).json()["results"]

        assert [entry["name"] for entry in oldest_first] == ["beta.txt", "alpha.txt", "gamma.md"]
        assert [entry["name"] for entry in found] == ["alpha.txt"]

    def test_search_finds_a_folder_by_a_file_deleted_inside_it(self, admin_client, real_manager, acme):
        seed_file(real_manager._backend, acme.id, "reports/2025/invoice-77.pdf", b"x")
        real_manager.delete(acme.id, "reports")
        _binned(real_manager, acme, "notes.txt")

        found = admin_client.get(BIN, {"search": "INVOICE"}).json()["results"]

        assert [entry["name"] for entry in found] == ["reports/"]

    def test_show_all_lists_every_file_of_a_folder_and_only_top_level_ids(
        self, admin_client, real_manager, acme, beta
    ):
        for index in range(3):
            seed_file(real_manager._backend, acme.id, f"docs/f{index}.txt", b"x")
        real_manager.delete(acme.id, "docs")
        folder, child = _row(acme, "docs/"), _row(acme, "docs/f0.txt")
        theirs = _binned(real_manager, beta, "theirs.txt")

        response = admin_client.get(f"{BIN}{folder.pk}/contents/")

        assert response.status_code == 200, response.content
        assert response.json() == {
            "contents": [{"name": f"f{index}.txt", "kind": "file"} for index in range(3)],
            "contents_total": 3,
        }
        assert admin_client.get(f"{BIN}{child.pk}/contents/").status_code == 404
        assert admin_client.get(f"{BIN}{theirs.pk}/contents/").status_code == 404

    def test_filter_by_kind(self, admin_client, real_manager, acme):
        _binned(real_manager, acme, "loose.txt")
        seed_file(real_manager._backend, acme.id, "docs/a.txt", b"a")
        real_manager.delete(acme.id, "docs")

        folders = admin_client.get(BIN, {"item_type": "folder"}).json()["results"]
        files = admin_client.get(BIN, {"item_type": "file"}).json()["results"]

        assert [entry["name"] for entry in folders] == ["docs/"]
        assert [entry["name"] for entry in files] == ["loose.txt"]  # docs/a.txt goes with its folder

    @pytest.mark.parametrize("action", ["restore", "purge"])
    def test_another_orgs_id_is_404_and_nothing_changes(self, admin_client, real_manager, acme, beta, action):
        ours = _binned(real_manager, acme, "ours.txt")
        theirs = _binned(real_manager, beta, "theirs.txt")

        for ids in ([theirs.pk], [ours.pk, theirs.pk]):
            response = admin_client.post(f"{BIN}{action}/", {"ids": ids}, format="json")
            assert response.status_code == 404, (ids, response.content)
        assert StorageFile.deleted_objects.filter(pk__in=[ours.pk, theirs.pk]).count() == 2

    @pytest.mark.parametrize("action", ["restore", "purge"])
    def test_a_live_id_is_404(self, admin_client, real_manager, acme, action):
        seed_file(real_manager._backend, acme.id, "a.txt", b"a")

        response = admin_client.post(f"{BIN}{action}/", {"ids": [_row(acme, "a.txt").pk]}, format="json")

        assert response.status_code == 404

    @pytest.mark.parametrize("ids", [[], list(range(1, 102))], ids=["empty", "101"])
    def test_id_count_is_bounded(self, admin_client, real_manager, ids):
        assert admin_client.post(f"{BIN}restore/", {"ids": ids}, format="json").status_code == 400

    def test_split_permissions(self, client_with_files_bits, real_manager, acme):
        row = _binned(real_manager, acme, "a.txt")
        reader = client_with_files_bits(Permission.READ)
        restorer = client_with_files_bits(Permission.READ | Permission.CREATE)
        purger = client_with_files_bits(Permission.READ | Permission.DELETE)
        blind = client_with_files_bits(Permission.CREATE | Permission.DELETE)

        assert reader.get(BIN).status_code == 200
        assert blind.get(BIN).status_code == 403
        assert reader.post(f"{BIN}restore/", {"ids": [row.pk]}, format="json").status_code == 403
        assert reader.post(f"{BIN}purge/", {"ids": [row.pk]}, format="json").status_code == 403
        assert restorer.post(f"{BIN}purge/", {"ids": [row.pk]}, format="json").status_code == 403
        assert purger.post(f"{BIN}restore/", {"ids": [row.pk]}, format="json").status_code == 403
        assert restorer.post(f"{BIN}restore/", {"ids": [row.pk]}, format="json").status_code == 200
        real_manager.delete(acme.id, "a.txt")
        again = StorageFile.deleted_objects.get(org=acme, path="a.txt")
        assert purger.post(f"{BIN}purge/", {"ids": [again.pk]}, format="json").status_code == 200


@pytest.mark.parametrize("method, url", [("get", BIN), ("post", f"{BIN}restore/"), ("post", f"{BIN}purge/")])
def test_a_request_without_the_org_header_is_400(client_as, admin_acme, real_manager, method, url):
    response = getattr(client_as(admin_acme), method)(url, {"ids": [1]}, format="json")

    assert response.status_code == 400
    assert response.json()["code"] == "org_context_required"


class TestFailures:
    def test_a_copy_failing_midway_through_a_restore_leaves_nothing_at_the_live_path(
        self, manager, service, org, monkeypatch
    ):
        seed_file(manager._backend, org.id, "docs/a.txt", b"a")
        seed_file(manager._backend, org.id, "docs/b.txt", b"b")
        manager.delete(org.id, "docs")
        folder_id = _row(org, "docs/").pk
        real_rename = manager._backend.rename

        def copy_one_then_fail(source, destination):
            manager._backend.put_bytes(destination + "/a.txt", b"a")  # one object landed
            raise RuntimeError("storage went away")

        monkeypatch.setattr(manager._backend, "rename", copy_one_then_fail)
        with pytest.raises(RuntimeError):
            service.restore(org.id, folder_id)

        assert not any(key.startswith(f"org_{org.id}/docs/") for key in _objects(manager))
        assert _row(org, "docs/").active is False

        monkeypatch.setattr(manager._backend, "rename", real_rename)
        service.restore(org.id, folder_id)  # a retry isn't blocked by a leftover copy
        assert _row(org, "docs/b.txt").active is True

    def test_a_storage_failure_during_purge_brings_the_rows_back(self, manager, service, org, monkeypatch):
        seed_file(manager._backend, org.id, "a.txt", b"a")
        batch = manager.delete(org.id, "a.txt")
        row = _row(org, "a.txt")
        monkeypatch.setattr(manager._backend, "delete_prefix", lambda prefix: (_ for _ in ()).throw(RuntimeError("down")))

        with pytest.raises(RuntimeError):
            service.purge(org.id, row.pk, actor="test")

        assert StorageFile.deleted_objects.filter(pk=row.pk).exists()
        assert _trash_keys(manager, org, batch) != []

    def test_restore_many_reports_a_conflict_and_keeps_the_others(self, manager, service, org):
        first = _binned(manager, org, "first.txt")
        second = _binned(manager, org, "second.txt")
        manager._backend.put_bytes(f"org_{org.id}/second.txt", b"stray")

        result = service.restore_many(org.id, [first.pk, second.pk])

        assert [restored.object.pk for restored in result.restored] == [first.pk]
        assert [failure.id for failure in result.failed] == [second.pk]
        assert StorageFile.objects.filter(pk=first.pk).exists()
        assert StorageFile.deleted_objects.filter(pk=second.pk).exists()
