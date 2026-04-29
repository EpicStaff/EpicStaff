from tables.serializers.storage_serializers import (
    _normalize_path,
    StorageBulkDeleteSerializer,
    StorageRenameSerializer,
    StorageUploadSerializer,
)


class TestNormalizePath:
    def test_strips_trailing_slashes(self):
        assert _normalize_path("docs/") == "docs"

    def test_strips_multiple_trailing_slashes(self):
        assert _normalize_path("docs///") == "docs"

    def test_preserves_empty_string(self):
        assert _normalize_path("") == ""

    def test_preserves_path_without_trailing_slash(self):
        assert _normalize_path("docs/report.txt") == "docs/report.txt"


class TestStorageRenameSerializer:
    def test_rename_to_executable_extension_rejected(self):
        ser = StorageRenameSerializer(
            data={"from_path": "old.txt", "to_path": "evil.exe"}
        )
        assert not ser.is_valid()
        assert "to_path" in ser.errors

    def test_rename_to_normal_extension_accepted(self):
        ser = StorageRenameSerializer(
            data={"from_path": "old.txt", "to_path": "new.txt"}
        )
        assert ser.is_valid(), ser.errors

    def test_rename_strips_trailing_slash_from_paths(self):
        ser = StorageRenameSerializer(data={"from_path": "old/", "to_path": "new/"})
        assert ser.is_valid(), ser.errors
        assert ser.validated_data["from"] == "old"
        assert ser.validated_data["to"] == "new"


class TestStorageUploadSerializer:
    def test_rejects_empty_file_list(self):
        ser = StorageUploadSerializer(data={"path": "", "files": []})
        assert not ser.is_valid()
        assert "files" in ser.errors


class TestStorageBulkDeleteSerializer:
    def test_normalizes_all_paths(self):
        ser = StorageBulkDeleteSerializer(data={"paths": ["a/", "b/", "c"]})
        assert ser.is_valid(), ser.errors
        assert ser.validated_data["paths"] == ["a", "b", "c"]

    def test_rejects_empty_paths_list(self):
        ser = StorageBulkDeleteSerializer(data={"paths": []})
        assert not ser.is_valid()
