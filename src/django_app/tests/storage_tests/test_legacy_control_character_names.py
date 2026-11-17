"""An entry with a control character in its name stays operable as itself.

`check_new_name` blocks new entries; `sanitize_storage_path` (traversal-only)
is unchanged, so an old name still resolves for list/search/info/download/
delete/restore/rename-to-clean. Creating something new at a path still holding
the old name is refused.
"""

import pytest

from src.shared.epicstaff_storage.path_safety import sanitize_storage_path
from tables.models import StorageFile
from tables.services.storage_service.dataclasses import FileInfo
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.path_utils import check_new_name, storage_key, trash_storage_key
from tables.services.storage_service.recycle_bin import StorageRecycleBinService
from tests.storage_tests.storage_writes import store_object

LEGACY_NAME = "quarterly\x07report.txt"
LEGACY_PATH = f"docs/{LEGACY_NAME}"

CONTROL_CHARACTER_PATHS = [
    pytest.param("a\nb.txt", id="newline"),
    pytest.param("a\rb.txt", id="carriage-return"),
    pytest.param("a\tb.txt", id="tab"),
    pytest.param("a\x07b.txt", id="bell"),
    pytest.param("a\x1bb.txt", id="escape"),
    pytest.param("a\x7fb.txt", id="delete"),
    pytest.param("docs/a\nb/c.txt", id="inside-a-folder-segment"),
]


@pytest.fixture
def manager(fake_backend):
    return StorageManager(fake_backend)


@pytest.fixture
def recycle_bin(manager):
    return StorageRecycleBinService(manager)


def _seed_legacy_file(manager, fake_backend, org, content=b"legacy", path=LEGACY_PATH):
    """Store a file under a name the manager would now refuse to create."""
    manager.mkdir(org.id, "docs")
    store_object(fake_backend, org.id, path, content)


class TestSanitizationKeepsAcceptingControlCharacters:
    """`sanitize_storage_path` is unchanged: it rejects traversal, not names."""

    @pytest.mark.parametrize("path", CONTROL_CHARACTER_PATHS)
    def test_a_control_character_passes_through_unchanged(self, path):
        assert sanitize_storage_path(path, allow_empty=True, allow_leading_slash=True) == path

    @pytest.mark.parametrize("path", CONTROL_CHARACTER_PATHS)
    def test_the_same_name_is_refused_for_a_new_entry(self, path):
        with pytest.raises(ValueError, match="control character"):
            check_new_name(path)

    def test_a_null_byte_is_still_rejected_everywhere(self):
        # Null bytes can truncate a key in a C-level API; sanitization has always refused them.
        with pytest.raises(ValueError, match="null byte"):
            sanitize_storage_path("a\x00b.txt", allow_empty=True, allow_leading_slash=True)

    @pytest.mark.parametrize("path", CONTROL_CHARACTER_PATHS)
    def test_traversal_is_still_rejected_alongside_a_control_character(self, path):
        with pytest.raises(ValueError, match="escapes the target folder"):
            sanitize_storage_path(f"../{path}", allow_empty=True, allow_leading_slash=True)


@pytest.mark.django_db
class TestLegacyEntriesStayOperable:
    """Every read and lifecycle operation on the entry itself still reaches a pre-existing name."""

    def test_listing_its_folder_shows_it_next_to_a_clean_name(self, manager, fake_backend, org):
        _seed_legacy_file(manager, fake_backend, org)
        store_object(fake_backend, org.id, "docs/clean.txt", b"clean")

        items = manager.list_(org.id, "docs")

        assert {item.name for item in items} == {LEGACY_NAME, "clean.txt"}

    def test_searching_finds_it_by_the_readable_part_of_its_name(self, manager, fake_backend, org):
        _seed_legacy_file(manager, fake_backend, org)

        results, total = manager.search(org.id, "report")

        assert total == 1
        assert [result["path"] for result in results] == [LEGACY_PATH]
        assert results[0]["name"] == LEGACY_NAME

    def test_info_reports_it_at_its_stored_path(self, manager, fake_backend, org):
        _seed_legacy_file(manager, fake_backend, org, b"12345")

        result = manager.info(org.id, LEGACY_PATH)

        assert isinstance(result, FileInfo)
        assert (result.path, result.name, result.size) == (LEGACY_PATH, LEGACY_NAME, 5)

    def test_downloading_it_returns_its_bytes(self, manager, fake_backend, org):
        _seed_legacy_file(manager, fake_backend, org, b"legacy bytes")

        assert manager.download(org.id, LEGACY_PATH).content == b"legacy bytes"

    def test_deleting_it_moves_its_object_and_row_to_the_recycle_bin(
        self, manager, fake_backend, org, org_user
    ):
        _seed_legacy_file(manager, fake_backend, org)

        batch = manager.delete(org.id, LEGACY_PATH, user=org_user.user)

        assert not fake_backend.exists(storage_key(org.id, LEGACY_PATH))
        assert fake_backend.download(trash_storage_key(org.id, batch, LEGACY_PATH)) == b"legacy"
        assert StorageFile.deleted_objects.filter(org=org, path=LEGACY_PATH).exists()

    def test_restoring_it_from_the_recycle_bin_brings_it_back(
        self, manager, fake_backend, recycle_bin, org, org_user
    ):
        _seed_legacy_file(manager, fake_backend, org)
        row_id = StorageFile.objects.get(org=org, path=LEGACY_PATH).pk
        batch = manager.delete(org.id, LEGACY_PATH, user=org_user.user)

        result = recycle_bin.restore(org.id, row_id)

        assert (result.object.path, result.renamed_from) == (LEGACY_PATH, None)
        assert fake_backend.download(storage_key(org.id, LEGACY_PATH)) == b"legacy"
        assert not fake_backend.exists(trash_storage_key(org.id, batch, LEGACY_PATH))
        assert StorageFile.objects.get(org=org, path=LEGACY_PATH).active is True

    def test_deleting_a_folder_whose_name_holds_a_control_character_takes_its_contents(
        self, manager, fake_backend, org, org_user
    ):
        legacy_folder = "in\x07box"
        store_object(fake_backend, org.id, f"{legacy_folder}/a.txt", b"a")

        batch = manager.delete(org.id, legacy_folder, user=org_user.user)

        assert fake_backend.download(trash_storage_key(org.id, batch, f"{legacy_folder}/a.txt")) == b"a"
        assert StorageFile.objects.filter(org=org, path__startswith=legacy_folder).count() == 0

    def test_moving_a_file_into_a_folder_that_does_not_exist_yet_is_still_refused(
        self, manager, fake_backend, org, org_user
    ):
        store_object(fake_backend, org.id, "clean.txt", b"moved")

        with pytest.raises(ValueError, match="control character"):
            manager.move(org.id, "clean.txt", "new\x07folder", user=org_user.user)

        assert StorageFile.objects.filter(org=org, path="clean.txt").exists()

    def test_renaming_it_to_a_clean_name_is_how_a_user_cleans_it_up(
        self, manager, fake_backend, org, org_user
    ):
        _seed_legacy_file(manager, fake_backend, org)

        manager.rename(org.id, LEGACY_PATH, "docs/report.txt", user=org_user.user)

        assert fake_backend.download(storage_key(org.id, "docs/report.txt")) == b"legacy"
        assert not StorageFile.objects.filter(org=org, path=LEGACY_PATH).exists()

    def test_renaming_it_to_another_control_character_name_is_refused(
        self, manager, fake_backend, org, org_user
    ):
        _seed_legacy_file(manager, fake_backend, org)

        with pytest.raises(ValueError, match="control character"):
            manager.rename(org.id, LEGACY_PATH, "docs/still\x07bad.txt", user=org_user.user)

        assert fake_backend.download(storage_key(org.id, LEGACY_PATH)) == b"legacy"
        assert StorageFile.objects.filter(org=org, path=LEGACY_PATH).exists()


LEGACY_FOLDER = "in\x07box"


@pytest.mark.django_db
class TestOperationsInsideALegacyFolderAreRejectedByDesign:
    """Accepted limitation: creating something new under a legacy-named folder is refused.

    A destination path is judged whole, so the control character still rejects it.
    Renaming the folder itself to a clean name (last test here) is the supported fix.
    """

    def test_renaming_a_file_inside_a_legacy_folder_is_rejected(
        self, manager, fake_backend, org, org_user
    ):
        store_object(fake_backend, org.id, f"{LEGACY_FOLDER}/old.txt", b"kept")

        with pytest.raises(ValueError, match="control character"):
            manager.rename(
                org.id, f"{LEGACY_FOLDER}/old.txt", f"{LEGACY_FOLDER}/new.txt", user=org_user.user
            )

        assert fake_backend.download(storage_key(org.id, f"{LEGACY_FOLDER}/old.txt")) == b"kept"
        assert not StorageFile.objects.filter(org=org, path=f"{LEGACY_FOLDER}/new.txt").exists()

    def test_creating_a_clean_subfolder_inside_a_legacy_folder_is_rejected(
        self, manager, fake_backend, org, org_user
    ):
        store_object(fake_backend, org.id, f"{LEGACY_FOLDER}/kept.txt", b"kept")

        with pytest.raises(ValueError, match="control character"):
            manager.mkdir(org.id, f"{LEGACY_FOLDER}/clean", user=org_user.user)

        assert not StorageFile.objects.filter(
            org=org, path=f"{LEGACY_FOLDER}/clean/", item_type="folder"
        ).exists()

    def test_moving_a_file_into_a_legacy_folder_is_rejected(
        self, manager, fake_backend, org, org_user
    ):
        store_object(fake_backend, org.id, f"{LEGACY_FOLDER}/kept.txt", b"kept")
        store_object(fake_backend, org.id, "clean.txt", b"moved")

        with pytest.raises(ValueError, match="control character"):
            manager.move(org.id, "clean.txt", LEGACY_FOLDER, user=org_user.user)

        assert StorageFile.objects.filter(org=org, path="clean.txt").exists()
        assert not StorageFile.objects.filter(org=org, path=f"{LEGACY_FOLDER}/clean.txt").exists()

    def test_copying_a_file_into_a_legacy_folder_is_rejected(
        self, manager, fake_backend, org, org_user
    ):
        store_object(fake_backend, org.id, f"{LEGACY_FOLDER}/kept.txt", b"kept")
        store_object(fake_backend, org.id, "clean.txt", b"copied")

        with pytest.raises(ValueError, match="control character"):
            manager.copy(org.id, "clean.txt", LEGACY_FOLDER, user=org_user.user)

        assert not StorageFile.objects.filter(org=org, path=f"{LEGACY_FOLDER}/clean.txt").exists()

    def test_a_control_character_in_a_middle_segment_is_rejected(
        self, manager, fake_backend, org, org_user
    ):
        with pytest.raises(ValueError, match="control character"):
            manager.mkdir(org.id, "clean/also\x07bad/leaf", user=org_user.user)

        assert not StorageFile.objects.filter(org=org, path__startswith="clean/").exists()

    def test_renaming_the_legacy_folder_itself_to_a_clean_name_makes_its_contents_operable(
        self, manager, fake_backend, org, org_user
    ):
        store_object(fake_backend, org.id, f"{LEGACY_FOLDER}/kept.txt", b"kept")

        manager.rename(org.id, LEGACY_FOLDER, "clean_box", user=org_user.user)

        assert manager.download(org.id, "clean_box/kept.txt").content == b"kept"
        assert not StorageFile.objects.filter(org=org, path__startswith=LEGACY_FOLDER).exists()

        manager.mkdir(org.id, "clean_box/sub", user=org_user.user)

        assert StorageFile.objects.filter(
            org=org, path="clean_box/sub/", item_type="folder"
        ).exists()

    def test_moving_a_legacy_named_file_to_a_clean_folder_is_rejected(
        self, manager, fake_backend, org, org_user
    ):
        # Moving keeps the entry's own name, so it carries the control character along.
        store_object(fake_backend, org.id, LEGACY_PATH, b"legacy")

        with pytest.raises(ValueError, match="control character"):
            manager.move(org.id, LEGACY_PATH, "clean", user=org_user.user)

        assert not StorageFile.objects.filter(org=org, path=f"clean/{LEGACY_NAME}").exists()
        assert StorageFile.objects.filter(org=org, path=LEGACY_PATH).exists()

    def test_copying_a_legacy_named_file_to_a_clean_folder_is_rejected(
        self, manager, fake_backend, org, org_user
    ):
        store_object(fake_backend, org.id, LEGACY_PATH, b"legacy")

        with pytest.raises(ValueError, match="control character"):
            manager.copy(org.id, LEGACY_PATH, "clean", user=org_user.user)

        assert not StorageFile.objects.filter(org=org, path=f"clean/{LEGACY_NAME}").exists()
