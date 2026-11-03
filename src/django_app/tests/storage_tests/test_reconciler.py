
import pytest

from rbac.models import Organization
from tables.models import StorageFile
from tables.services.storage_service.reconciler import StorageReconciler
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend


pytestmark = pytest.mark.django_db


@pytest.fixture
def org(db):
    return Organization.objects.create(name="reconciler-org")


@pytest.fixture
def fake_manager_backend():
    """InMemoryStorageBackend with empty prefix — mirrors how get_storage_manager() sets it up."""
    return InMemoryStorageBackend(organization_prefix="")


def _seed_file(backend, org_id, rel_path, content=b"data"):
    """Store a file under org_<id>/<rel_path> in the backend."""
    backend.put_bytes(f"org_{org_id}/{rel_path}", content)


class TestReconcileTree:
    def test_creates_file_rows_with_size_and_parent_path(
        self, org, fake_manager_backend
    ):
        _seed_file(fake_manager_backend, org.id, "a/b/file.txt", content=b"hello")
        StorageReconciler(fake_manager_backend).reconcile_tree(org.id, "")

        row = StorageFile.objects.get(org=org, path="a/b/file.txt")
        assert row.item_type == "file"
        assert row.size == 5
        assert row.parent_path == "a/b/"
        assert row.name == "file.txt"

    def test_creates_ancestor_folder_rows(self, org, fake_manager_backend):
        _seed_file(fake_manager_backend, org.id, "a/b/file.txt")
        StorageReconciler(fake_manager_backend).reconcile_tree(org.id, "")

        assert StorageFile.objects.filter(
            org=org, path="a/", item_type="folder"
        ).exists()
        assert StorageFile.objects.filter(
            org=org, path="a/b/", item_type="folder"
        ).exists()

    def test_deletes_stale_rows(self, org, fake_manager_backend):
        StorageFile.objects.create(
            org=org, path="ghost.txt", name="ghost.txt", item_type="file"
        )
        _seed_file(fake_manager_backend, org.id, "real.txt")
        StorageReconciler(fake_manager_backend).reconcile_tree(org.id, "")

        assert not StorageFile.objects.filter(org=org, path="ghost.txt").exists()
        assert StorageFile.objects.filter(org=org, path="real.txt").exists()

    def test_preserves_is_system_and_created_at_across_rerun(
        self, org, fake_manager_backend
    ):
        _seed_file(fake_manager_backend, org.id, "out.txt", content=b"x")
        StorageReconciler(fake_manager_backend).reconcile_tree(org.id, "")

        row = StorageFile.objects.get(org=org, path="out.txt")
        original_created_at = row.created_at
        row.is_system = True
        row.save(update_fields=["is_system"])

        StorageReconciler(fake_manager_backend).reconcile_tree(org.id, "")

        row.refresh_from_db()
        assert row.is_system is True
        assert row.created_at == original_created_at

    def test_root_prefix_empty_string(self, org, fake_manager_backend):
        _seed_file(fake_manager_backend, org.id, "root_file.txt")
        StorageReconciler(fake_manager_backend).reconcile_tree(org.id, "")

        assert StorageFile.objects.filter(org=org, path="root_file.txt").exists()

    def test_folder_rows_have_correct_parent_path(self, org, fake_manager_backend):
        _seed_file(fake_manager_backend, org.id, "x/y/z/deep.txt")
        StorageReconciler(fake_manager_backend).reconcile_tree(org.id, "")

        folder = StorageFile.objects.get(org=org, path="x/y/")
        assert folder.parent_path == "x/"
        assert folder.item_type == "folder"


class TestReconcileFile:
    """A single granted file is read directly: reconcile_tree lists `<path>/`, which for a
    file path finds nothing and would sweep the file's own row."""

    def test_indexes_the_file_at_its_stored_size_with_its_folders(self, org, fake_manager_backend):
        _seed_file(fake_manager_backend, org.id, "reports/q1.csv", content=b"12345")

        StorageReconciler(fake_manager_backend).reconcile_file(org.id, "reports/q1.csv")

        row = StorageFile.objects.get(org=org, path="reports/q1.csv")
        assert (row.item_type, row.size) == ("file", 5)
        assert StorageFile.objects.filter(org=org, path="reports/", item_type="folder").exists()

    def test_updates_a_row_whose_size_drifted(self, org, fake_manager_backend):
        StorageFile.objects.create(
            org=org, path="q1.csv", name="q1.csv", item_type="file", size=1
        )
        _seed_file(fake_manager_backend, org.id, "q1.csv", content=b"12345")

        StorageReconciler(fake_manager_backend).reconcile_file(org.id, "q1.csv")

        assert StorageFile.objects.get(org=org, path="q1.csv").size == 5

    def test_leaves_other_objects_sharing_the_path_as_a_prefix_alone(
        self, org, fake_manager_backend
    ):
        _seed_file(fake_manager_backend, org.id, "q1.csv", content=b"12345")
        _seed_file(fake_manager_backend, org.id, "q1.csv.bak", content=b"zzz")

        StorageReconciler(fake_manager_backend).reconcile_file(org.id, "q1.csv")

        assert set(StorageFile.objects.filter(org=org).values_list("path", flat=True)) == {"q1.csv"}

    def test_drops_the_row_of_a_file_that_is_gone_and_keeps_its_neighbours(
        self, org, fake_manager_backend
    ):
        StorageFile.objects.create(org=org, path="gone.csv", name="gone.csv", item_type="file")
        StorageFile.objects.create(org=org, path="gone.csv.bak", name="gone.csv.bak", item_type="file")

        StorageReconciler(fake_manager_backend).reconcile_file(org.id, "gone.csv")

        assert set(StorageFile.objects.filter(org=org).values_list("path", flat=True)) == {
            "gone.csv.bak"
        }

    def test_never_indexes_an_executable_and_drops_a_live_row_for_one(
        self, org, fake_manager_backend
    ):
        StorageFile.objects.create(org=org, path="run.sh", name="run.sh", item_type="file")
        _seed_file(fake_manager_backend, org.id, "run.sh", content=b"echo hi")

        StorageReconciler(fake_manager_backend).reconcile_file(org.id, "run.sh")

        assert not StorageFile.objects.filter(org=org, path="run.sh").exists()
        assert f"org_{org.id}/run.sh" in fake_manager_backend._objects

    def test_refuses_a_path_in_the_recycle_bin(self, org, fake_manager_backend):
        with pytest.raises(ValueError):
            StorageReconciler(fake_manager_backend).reconcile_file(org.id, ".recycle-bin/x/a.txt")


class TestAddOnlyReconcile:
    def test_a_tree_reconcile_without_sweeping_keeps_rows_missing_from_the_listing(
        self, org, fake_manager_backend
    ):
        StorageFile.objects.create(
            org=org, path="dir/late.txt", name="late.txt", item_type="file", size=3
        )
        _seed_file(fake_manager_backend, org.id, "dir/real.txt", content=b"12345")

        StorageReconciler(fake_manager_backend).reconcile_tree(
            org.id, "dir/", sweep_stale_rows=False
        )

        rows = {r.path: r.size for r in StorageFile.objects.filter(org=org, item_type="file")}
        assert rows == {"dir/late.txt": 3, "dir/real.txt": 5}

    def test_a_tree_reconcile_without_sweeping_still_adds_and_updates(
        self, org, fake_manager_backend
    ):
        StorageFile.objects.create(org=org, path="a.txt", name="a.txt", item_type="file", size=1)
        _seed_file(fake_manager_backend, org.id, "a.txt", content=b"12345")

        StorageReconciler(fake_manager_backend).reconcile_tree(org.id, "", sweep_stale_rows=False)

        assert StorageFile.objects.get(org=org, path="a.txt").size == 5

    def test_a_file_reconcile_without_sweeping_keeps_the_row_of_a_missing_object(
        self, org, fake_manager_backend
    ):
        StorageFile.objects.create(org=org, path="gone.csv", name="gone.csv", item_type="file")

        StorageReconciler(fake_manager_backend).reconcile_file(
            org.id, "gone.csv", sweep_stale_rows=False
        )

        assert StorageFile.objects.filter(org=org, path="gone.csv").exists()
