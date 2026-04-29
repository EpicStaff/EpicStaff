from io import BytesIO

import pytest

from tables.services.storage_service.dataclasses import FileInfo, FolderInfo


class TestResolve:
    def test_resolve_raises_permission_error_on_path_traversal(self, local_backend):
        with pytest.raises(PermissionError, match="Path traversal"):
            local_backend._resolve("../../etc/passwd")

    def test_resolve_allows_nested_subdirectory_paths(self, local_backend):
        # Should not raise
        local_backend._resolve("a/b/c")


class TestList:
    def test_list_returns_empty_for_nonexistent_directory(self, local_backend):
        assert local_backend.list_("nonexistent") == []

    def test_list_returns_files_and_folders_sorted_by_name(
        self, local_backend, tmp_path
    ):
        (tmp_path / "b_file.txt").write_text("data")
        (tmp_path / "a_folder").mkdir()
        items = local_backend.list_("")
        assert [i.name for i in items] == ["a_folder", "b_file.txt"]
        assert items[0].type == "folder"
        assert items[1].type == "file"

    def test_list_reports_correct_size_for_files(self, local_backend, tmp_path):
        content = b"hello world"
        (tmp_path / "sized.txt").write_bytes(content)
        items = local_backend.list_("")
        assert items[0].size == len(content)

    def test_list_marks_empty_folder_is_empty_true(self, local_backend, tmp_path):
        (tmp_path / "empty_dir").mkdir()
        items = local_backend.list_("")
        assert items[0].is_empty is True

    def test_list_marks_nonempty_folder_is_empty_false(self, local_backend, tmp_path):
        d = tmp_path / "full_dir"
        d.mkdir()
        (d / "child.txt").write_text("x")
        items = local_backend.list_("")
        assert items[0].is_empty is False


class TestUploadDownload:
    def test_upload_creates_file_and_returns_correct_size(
        self, local_backend, tmp_path
    ):
        content = b"file content here"
        result = local_backend.upload("test.txt", BytesIO(content))
        assert result.size == len(content)
        assert (tmp_path / "test.txt").read_bytes() == content

    def test_upload_creates_parent_directories(self, local_backend, tmp_path):
        local_backend.upload("deep/nested/file.txt", BytesIO(b"data"))
        assert (tmp_path / "deep" / "nested" / "file.txt").exists()

    def test_download_returns_uploaded_bytes(self, local_backend):
        content = b"round trip content"
        local_backend.upload("round.txt", BytesIO(content))
        assert local_backend.download("round.txt") == content


class TestDelete:
    def test_delete_removes_file(self, local_backend, tmp_path):
        (tmp_path / "doomed.txt").write_text("bye")
        local_backend.delete("doomed.txt")
        assert not (tmp_path / "doomed.txt").exists()

    def test_delete_removes_directory_recursively(self, local_backend, tmp_path):
        d = tmp_path / "doomed_dir"
        d.mkdir()
        (d / "child.txt").write_text("x")
        local_backend.delete("doomed_dir")
        assert not d.exists()


class TestMkdir:
    def test_mkdir_creates_nested_directories(self, local_backend, tmp_path):
        local_backend.mkdir("a/b/c")
        assert (tmp_path / "a" / "b" / "c").is_dir()

    def test_mkdir_is_idempotent(self, local_backend):
        local_backend.mkdir("repeat")
        local_backend.mkdir("repeat")  # no error


class TestMove:
    def test_move_places_source_inside_destination_directory(
        self, local_backend, tmp_path
    ):
        (tmp_path / "src.txt").write_bytes(b"data")
        local_backend.move("src.txt", "dest_dir")
        assert (tmp_path / "dest_dir" / "src.txt").read_bytes() == b"data"
        assert not (tmp_path / "src.txt").exists()

    def test_move_raises_file_not_found_for_missing_source(self, local_backend):
        with pytest.raises(FileNotFoundError):
            local_backend.move("ghost.txt", "dest")


class TestRename:
    def test_rename_moves_to_exact_destination_path(self, local_backend, tmp_path):
        (tmp_path / "old.txt").write_bytes(b"data")
        local_backend.rename("old.txt", "new.txt")
        assert (tmp_path / "new.txt").read_bytes() == b"data"
        assert not (tmp_path / "old.txt").exists()

    def test_rename_raises_file_exists_when_destination_exists(
        self, local_backend, tmp_path
    ):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        with pytest.raises(FileExistsError):
            local_backend.rename("a.txt", "b.txt")

    def test_rename_raises_file_not_found_for_missing_source(self, local_backend):
        with pytest.raises(FileNotFoundError):
            local_backend.rename("ghost.txt", "new.txt")


class TestCopy:
    def test_copy_file_into_destination_returns_single_path(
        self, local_backend, tmp_path
    ):
        (tmp_path / "orig.txt").write_bytes(b"data")
        (tmp_path / "target").mkdir()
        paths = local_backend.copy("orig.txt", "target")
        assert len(paths) == 1
        assert (tmp_path / "target" / "orig.txt").read_bytes() == b"data"

    def test_copy_folder_returns_all_nested_file_paths(self, local_backend, tmp_path):
        src = tmp_path / "folder"
        src.mkdir()
        (src / "a.txt").write_text("a")
        sub = src / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("b")
        (tmp_path / "dest").mkdir()
        paths = local_backend.copy("folder", "dest")
        assert len(paths) == 2

    def test_copy_appends_increment_suffix_on_name_conflict(
        self, local_backend, tmp_path
    ):
        (tmp_path / "file.txt").write_bytes(b"data")
        (tmp_path / "dest").mkdir()
        # First copy
        local_backend.copy("file.txt", "dest")
        # Second copy — should get " (1)" suffix
        paths = local_backend.copy("file.txt", "dest")
        assert any("(1)" in p for p in paths)


class TestInfo:
    def test_info_returns_file_info_with_size_and_content_type(
        self, local_backend, tmp_path
    ):
        content = b"info test"
        (tmp_path / "doc.txt").write_bytes(content)
        info = local_backend.info("doc.txt")
        assert isinstance(info, FileInfo)
        assert info.size == len(content)
        assert info.name == "doc.txt"
        assert "text" in info.content_type

    def test_info_returns_folder_info_with_trailing_slash(
        self, local_backend, tmp_path
    ):
        (tmp_path / "mydir").mkdir()
        info = local_backend.info("mydir")
        assert isinstance(info, FolderInfo)
        assert info.path.endswith("/")

    def test_info_raises_file_not_found_for_missing_path(self, local_backend):
        with pytest.raises(FileNotFoundError):
            local_backend.info("ghost")


class TestExists:
    def test_exists_true_for_existing_file(self, local_backend, tmp_path):
        (tmp_path / "here.txt").write_text("x")
        assert local_backend.exists("here.txt") is True

    def test_exists_false_for_missing_path(self, local_backend):
        assert local_backend.exists("nope.txt") is False


class TestListAllKeys:
    def test_list_all_keys_returns_files_recursively_excludes_dirs(
        self, local_backend, tmp_path
    ):
        d = tmp_path / "root"
        d.mkdir()
        (d / "a.txt").write_text("a")
        sub = d / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("b")
        keys = local_backend.list_all_keys("root")
        assert len(keys) == 2
        assert all("txt" in k for k in keys)

    def test_list_all_keys_returns_empty_for_missing_directory(self, local_backend):
        assert local_backend.list_all_keys("nope") == []


class TestUploadArchive:
    def test_upload_archive_extracts_zip_into_named_folder(
        self, local_backend, sample_zip
    ):
        paths = local_backend.upload_archive("", sample_zip, "sample.zip")
        assert len(paths) == 2
        assert any("hello.txt" in p for p in paths)

    def test_upload_archive_extracts_tar_into_named_folder(
        self, local_backend, sample_tar
    ):
        paths = local_backend.upload_archive("", sample_tar, "sample.tar")
        assert len(paths) == 2

    def test_upload_archive_increments_folder_name_on_conflict(
        self, local_backend, tmp_path, sample_zip
    ):
        # Create the folder that would be the default extract target
        (tmp_path / "sample").mkdir()
        paths = local_backend.upload_archive("", sample_zip, "sample.zip")
        # Should have created "sample (1)" instead
        assert any("sample (1)" in p for p in paths)

    def test_upload_archive_rejects_password_protected_zip(
        self, local_backend, password_zip
    ):
        with pytest.raises(ValueError, match="protected"):
            local_backend.upload_archive("", password_zip, "encrypted.zip")
