import zipfile
from io import BytesIO

import pytest

from tables.services.storage_service.dataclasses import FileInfo, FolderInfo


class TestList:
    def test_list_returns_empty_for_nonexistent_directory(self, fake_backend):
        assert fake_backend.list_("nonexistent") == []

    def test_list_returns_files_and_folders(self, fake_backend):
        fake_backend.upload("b_file.txt", BytesIO(b"data"))
        fake_backend.mkdir("a_folder")
        items = fake_backend.list_("")
        names_by_type = {i.name: i.type for i in items}
        assert names_by_type == {"a_folder": "folder", "b_file.txt": "file"}

    def test_list_reports_correct_size_for_files(self, fake_backend):
        content = b"hello world"
        fake_backend.upload("sized.txt", BytesIO(content))
        items = fake_backend.list_("")
        assert items[0].size == len(content)

    def test_list_marks_empty_folder_is_empty_true(self, fake_backend):
        fake_backend.mkdir("empty_dir")
        items = fake_backend.list_("")
        assert items[0].is_empty is True

    def test_list_marks_nonempty_folder_is_empty_false(self, fake_backend):
        fake_backend.mkdir("full_dir")
        fake_backend.upload("full_dir/child.txt", BytesIO(b"x"))
        items = fake_backend.list_("")
        folder = next(i for i in items if i.name == "full_dir")
        assert folder.is_empty is False


class TestUploadDownload:
    def test_upload_creates_file_and_returns_correct_size(self, fake_backend):
        content = b"file content here"
        result = fake_backend.upload("test.txt", BytesIO(content))
        assert result.size == len(content)
        assert fake_backend.download("test.txt") == content

    def test_upload_creates_parent_directories_implicitly(self, fake_backend):
        fake_backend.upload("deep/nested/file.txt", BytesIO(b"data"))
        assert fake_backend.exists("deep/nested/file.txt")

    def test_download_returns_uploaded_bytes(self, fake_backend):
        content = b"round trip content"
        fake_backend.upload("round.txt", BytesIO(content))
        assert fake_backend.download("round.txt") == content

    def test_download_raises_file_not_found_for_missing_path(self, fake_backend):
        with pytest.raises(FileNotFoundError):
            fake_backend.download("ghost.txt")


class TestDelete:
    def test_delete_removes_file(self, fake_backend):
        fake_backend.upload("doomed.txt", BytesIO(b"bye"))
        fake_backend.delete("doomed.txt")
        assert not fake_backend.exists("doomed.txt")

    def test_delete_removes_directory_recursively(self, fake_backend):
        fake_backend.mkdir("doomed_dir")
        fake_backend.upload("doomed_dir/child.txt", BytesIO(b"x"))
        fake_backend.delete("doomed_dir")
        assert fake_backend.list_all_keys("doomed_dir") == []
        assert not fake_backend.exists("doomed_dir/")


class TestMkdir:
    def test_mkdir_creates_nested_directories(self, fake_backend):
        fake_backend.mkdir("a/b/c")
        assert fake_backend.exists("a/b/c/")

    def test_mkdir_is_idempotent(self, fake_backend):
        fake_backend.mkdir("repeat")
        fake_backend.mkdir("repeat")  # no error


class TestMove:
    def test_move_places_source_inside_destination_directory(self, fake_backend):
        fake_backend.upload("src.txt", BytesIO(b"data"))
        fake_backend.mkdir("dest_dir")
        actual_path = fake_backend.move("src.txt", "dest_dir")
        assert actual_path == "dest_dir/src.txt"
        assert fake_backend.download("dest_dir/src.txt") == b"data"
        assert not fake_backend.exists("src.txt")

    def test_move_returns_deduped_folder_base_ending_in_slash(self, fake_backend):
        fake_backend.upload("docs/a.txt", BytesIO(b"a"))
        fake_backend.mkdir("archive/docs")
        actual_base = fake_backend.move("docs", "archive")
        assert actual_base == "archive/docs (1)/"
        assert fake_backend.download("archive/docs (1)/a.txt") == b"a"

    def test_move_raises_file_not_found_for_missing_source(self, fake_backend):
        with pytest.raises(FileNotFoundError):
            fake_backend.move("ghost.txt", "dest")


class TestRename:
    def test_rename_moves_to_exact_destination_path(self, fake_backend):
        fake_backend.upload("old.txt", BytesIO(b"data"))
        fake_backend.rename("old.txt", "new.txt")
        assert fake_backend.download("new.txt") == b"data"
        assert not fake_backend.exists("old.txt")

    def test_rename_raises_file_exists_when_destination_exists(self, fake_backend):
        fake_backend.upload("a.txt", BytesIO(b"a"))
        fake_backend.upload("b.txt", BytesIO(b"b"))
        with pytest.raises(FileExistsError):
            fake_backend.rename("a.txt", "b.txt")

    def test_rename_raises_file_not_found_for_missing_source(self, fake_backend):
        with pytest.raises(FileNotFoundError):
            fake_backend.rename("ghost.txt", "new.txt")

    def test_rename_raises_value_error_for_same_path(self, fake_backend):
        fake_backend.upload("same.txt", BytesIO(b"x"))
        with pytest.raises(ValueError):
            fake_backend.rename("same.txt", "same.txt")


class TestCopy:
    def test_copy_file_into_destination_returns_single_path(self, fake_backend):
        fake_backend.upload("orig.txt", BytesIO(b"data"))
        fake_backend.mkdir("target")
        paths = fake_backend.copy("orig.txt", "target")
        assert paths == ["target/orig.txt"]
        assert fake_backend.download("target/orig.txt") == b"data"

    def test_copy_folder_returns_all_nested_file_paths(self, fake_backend):
        fake_backend.upload("folder/a.txt", BytesIO(b"a"))
        fake_backend.upload("folder/sub/b.txt", BytesIO(b"b"))
        fake_backend.mkdir("dest")
        paths = fake_backend.copy("folder", "dest")
        assert set(paths) == {"dest/folder/a.txt", "dest/folder/sub/b.txt"}

    def test_copy_appends_increment_suffix_on_name_conflict(self, fake_backend):
        fake_backend.upload("file.txt", BytesIO(b"data"))
        fake_backend.mkdir("dest")
        fake_backend.copy("file.txt", "dest")
        paths = fake_backend.copy("file.txt", "dest")
        assert paths == ["dest/file (1).txt"]

    def test_copy_raises_file_not_found_for_missing_source(self, fake_backend):
        with pytest.raises(FileNotFoundError):
            fake_backend.copy("ghost.txt", "dest")


class TestInfo:
    def test_info_returns_file_info_with_size_and_content_type(self, fake_backend):
        content = b"info test"
        fake_backend.upload("doc.txt", BytesIO(content))
        info = fake_backend.info("doc.txt")
        assert isinstance(info, FileInfo)
        assert info.size == len(content)
        assert info.name == "doc.txt"
        assert "text" in info.content_type

    def test_info_returns_folder_info_with_trailing_slash(self, fake_backend):
        fake_backend.mkdir("mydir")
        info = fake_backend.info("mydir")
        assert isinstance(info, FolderInfo)
        assert info.path.endswith("/")

    def test_info_raises_file_not_found_for_missing_path(self, fake_backend):
        with pytest.raises(FileNotFoundError):
            fake_backend.info("ghost")


class TestExists:
    def test_exists_true_for_existing_file(self, fake_backend):
        fake_backend.upload("here.txt", BytesIO(b"x"))
        assert fake_backend.exists("here.txt") is True

    def test_exists_false_for_missing_path(self, fake_backend):
        assert fake_backend.exists("nope.txt") is False


class TestListAllKeys:
    def test_list_all_keys_returns_files_recursively_excludes_dirs(self, fake_backend):
        fake_backend.upload("root/a.txt", BytesIO(b"a"))
        fake_backend.upload("root/sub/b.txt", BytesIO(b"b"))
        keys = fake_backend.list_all_keys("root")
        assert len(keys) == 2
        assert all("txt" in k for k in keys)

    def test_list_all_keys_returns_empty_for_missing_directory(self, fake_backend):
        assert fake_backend.list_all_keys("nope") == []


class TestListTree:
    def test_tree_returns_empty_for_empty_folder(self, fake_backend):
        fake_backend.mkdir("empty")
        root, truncated = fake_backend.list_tree("empty")
        assert root.type == "folder"
        assert root.children == []
        assert truncated is False

    def test_tree_nests_files_and_folders(self, fake_backend):
        fake_backend.upload("reports/q1.pdf", BytesIO(b"x" * 10))
        fake_backend.upload("reports/2025/summary.txt", BytesIO(b"s"))

        root, _ = fake_backend.list_tree("reports")
        names = sorted(c.name for c in root.children)
        assert names == ["2025", "q1.pdf"]
        year = next(c for c in root.children if c.name == "2025")
        assert year.children[0].name == "summary.txt"

    def test_tree_respects_max_depth(self, fake_backend):
        fake_backend.upload("a/b/c/d/x.txt", BytesIO(b"x"))

        root, _ = fake_backend.list_tree("a", max_depth=2)
        depth = 0
        cur = root
        while cur.children:
            cur = cur.children[0]
            depth += 1
        assert depth == 2

    def test_tree_sets_truncated_when_over_max_entries(self, fake_backend):
        for i in range(10):
            fake_backend.upload(f"f{i}.txt", BytesIO(b""))
        root, truncated = fake_backend.list_tree("", max_entries=3)
        assert truncated is True
        assert len(root.children) <= 3


class TestUploadArchive:
    def test_upload_archive_extracts_zip_into_named_folder(
        self, fake_backend, sample_zip
    ):
        paths = fake_backend.upload_archive("", sample_zip, "sample.zip")
        assert len(paths) == 2
        assert any("hello.txt" in p for p in paths)

    def test_upload_archive_extracts_tar_into_named_folder(
        self, fake_backend, sample_tar
    ):
        paths = fake_backend.upload_archive("", sample_tar, "sample.tar")
        assert len(paths) == 2

    def test_upload_archive_increments_folder_name_on_conflict(
        self, fake_backend, sample_zip
    ):
        fake_backend.mkdir("sample")
        paths = fake_backend.upload_archive("", sample_zip, "sample.zip")
        assert any("sample (1)" in p for p in paths)

    def test_upload_archive_rejects_password_protected_zip(
        self, fake_backend, password_zip
    ):
        with pytest.raises(ValueError, match="protected"):
            fake_backend.upload_archive("", password_zip, "encrypted.zip")

    def test_upload_archive_rejects_zip_slip_and_writes_nothing(self, fake_backend):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            # Malicious entry is written first so the generator fails before
            # any legitimate entry gets extracted, proving there is no
            # partial extraction on the way to the ValueError.
            zf.writestr("../evil.txt", "evil content")
            zf.writestr("safe.txt", "safe content")
        buf.seek(0)

        with pytest.raises(ValueError, match="escapes the target folder"):
            fake_backend.upload_archive("", buf, "malicious.zip")

        assert fake_backend._objects == {}

    def test_upload_archive_rejects_traversal_in_archive_name(
        self, fake_backend, sample_zip
    ):
        with pytest.raises(ValueError, match="escapes the target folder"):
            fake_backend.upload_archive(
                "org_1/uploads", sample_zip, "../org_2/evil.zip"
            )

        assert fake_backend._objects == {}
