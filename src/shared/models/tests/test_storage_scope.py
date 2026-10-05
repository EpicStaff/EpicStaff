"""Unit tests for storage credentials and storage-scoped data models."""

import pytest
from shared.models.storage_scope import StorageCredentials, StorageScopedData
from shared.models.tools import CodeTaskData, PythonCodeData
from shared.models.graph_nodes import FileExtractorNodeData, AudioTranscriptionNodeData


class TestStorageCredentials:
    """Tests for StorageCredentials model."""

    def test_creation_with_both_keys(self):
        """StorageCredentials should accept access_key and secret_key."""
        creds = StorageCredentials(
            access_key="test-access-key",
            secret_key="test-secret-key",
        )
        assert creds.access_key == "test-access-key"
        assert creds.secret_key == "test-secret-key"

    def test_secret_key_not_excluded(self):
        """secret_key should be present in the model, never auto-excluded."""
        creds = StorageCredentials(
            access_key="access",
            secret_key="secret",
        )
        data = creds.model_dump()
        assert "secret_key" in data
        assert data["secret_key"] == "secret"

    def test_from_attributes(self):
        """StorageCredentials should support from_attributes config."""
        class FakeObj:
            access_key = "attr-access"
            secret_key = "attr-secret"

        creds = StorageCredentials.model_validate(FakeObj(), from_attributes=True)
        assert creds.access_key == "attr-access"
        assert creds.secret_key == "attr-secret"


class TestStorageScopedData:
    """Tests for StorageScopedData mixin."""

    def test_mixin_has_scope_fields(self):
        """StorageScopedData should define all scope fields."""
        # Create a subclass to test the mixin
        class ScopedModel(StorageScopedData):
            name: str

        model = ScopedModel(
            name="test",
            use_storage=True,
            storage_allowed_paths=["/path1"],
            storage_org_prefix="org_123",
            session_id=1,
            org_id=5,
        )
        assert model.use_storage is True
        assert model.storage_allowed_paths == ["/path1"]
        assert model.storage_org_prefix == "org_123"
        assert model.session_id == 1
        assert model.org_id == 5

    def test_mixin_defaults(self):
        """StorageScopedData fields should have correct defaults."""
        class ScopedModel(StorageScopedData):
            name: str

        model = ScopedModel(name="test")
        assert model.use_storage is False
        assert model.storage_allowed_paths is None
        assert model.storage_org_prefix is None
        assert model.session_id is None
        assert model.org_id is None


class TestPythonCodeData:
    """Tests for PythonCodeData inheriting from StorageScopedData."""

    def test_inherits_scope_fields(self):
        """PythonCodeData should inherit scope fields from StorageScopedData."""
        code = PythonCodeData(
            venv_name="test-venv",
            code="print('hello')",
            entrypoint="main",
            libraries=["requests"],
            use_storage=True,
            storage_allowed_paths=["/data"],
            storage_org_prefix="org_42",
            session_id=10,
            org_id=3,
        )
        assert code.use_storage is True
        assert code.storage_allowed_paths == ["/data"]
        assert code.storage_org_prefix == "org_42"
        assert code.session_id == 10
        assert code.org_id == 3

    def test_no_storage_credentials_field(self):
        """PythonCodeData should NOT have storage_credentials field (it's a graph node)."""
        code = PythonCodeData(
            venv_name="test-venv",
            code="print('hello')",
            entrypoint="main",
            libraries=["requests"],
        )
        assert not hasattr(code, "storage_credentials")
        data = code.model_dump()
        assert "storage_credentials" not in data


class TestCodeTaskData:
    """Tests for CodeTaskData inheriting from StorageScopedData and adding storage_credentials."""

    def test_inherits_scope_fields(self):
        """CodeTaskData should inherit scope fields from StorageScopedData."""
        task = CodeTaskData(
            venv_name="test-venv",
            libraries=["requests"],
            code="print('hello')",
            execution_id="exec-123",
            entrypoint="main",
            use_storage=True,
            storage_allowed_paths=["/data"],
            storage_org_prefix="org_42",
            session_id=10,
            org_id=3,
        )
        assert task.use_storage is True
        assert task.storage_allowed_paths == ["/data"]
        assert task.storage_org_prefix == "org_42"
        assert task.session_id == 10
        assert task.org_id == 3

    def test_has_storage_credentials_field(self):
        """CodeTaskData should have storage_credentials field."""
        creds = StorageCredentials(
            access_key="access",
            secret_key="secret",
        )
        task = CodeTaskData(
            venv_name="test-venv",
            libraries=["requests"],
            code="print('hello')",
            execution_id="exec-123",
            entrypoint="main",
            storage_credentials=creds,
        )
        assert task.storage_credentials is not None
        assert task.storage_credentials.access_key == "access"

    def test_storage_credentials_optional(self):
        """storage_credentials should default to None."""
        task = CodeTaskData(
            venv_name="test-venv",
            libraries=["requests"],
            code="print('hello')",
            execution_id="exec-123",
            entrypoint="main",
        )
        assert task.storage_credentials is None

    def test_log_summary_does_not_include_secret_key(self):
        """log_summary() should not include secret_key value."""
        creds = StorageCredentials(
            access_key="secret-access-key",
            secret_key="secret-key-value",
        )
        task = CodeTaskData(
            venv_name="test-venv",
            libraries=["lib1", "lib2"],
            code="print('hello')",
            execution_id="exec-123",
            entrypoint="main",
            storage_credentials=creds,
            secrets={"DBPASS": "very-secret-password"},
        )
        summary = task.log_summary()

        # Should NOT contain the actual secret_key value
        assert "secret-key-value" not in summary

        # Should NOT contain the actual secret values
        assert "very-secret-password" not in summary

        # Should contain safe information
        assert "exec-123" in summary
        assert "test-venv" in summary
        assert "main" in summary
        assert "libraries=2" in summary
        assert "secrets=1" in summary
        assert "storage_credentials=present" in summary

    def test_log_summary_without_storage_credentials(self):
        """log_summary() should indicate 'none' when storage_credentials is absent."""
        task = CodeTaskData(
            venv_name="test-venv",
            libraries=["requests"],
            code="print('hello')",
            execution_id="exec-456",
            entrypoint="main",
            storage_credentials=None,
        )
        summary = task.log_summary()
        assert "storage_credentials=none" in summary

    def test_validator_requires_org_id_when_use_storage(self):
        """CodeTaskData should require org_id when use_storage=True."""
        with pytest.raises(ValueError, match="org_id and storage_org_prefix"):
            CodeTaskData(
                venv_name="test-venv",
                libraries=["requests"],
                code="print('hello')",
                execution_id="exec-123",
                entrypoint="main",
                use_storage=True,
                storage_allowed_paths=["/data"],
                # Missing org_id and storage_org_prefix
            )

    def test_validator_requires_storage_org_prefix_when_use_storage(self):
        """CodeTaskData should require storage_org_prefix when use_storage=True."""
        with pytest.raises(ValueError, match="org_id and storage_org_prefix"):
            CodeTaskData(
                venv_name="test-venv",
                libraries=["requests"],
                code="print('hello')",
                execution_id="exec-123",
                entrypoint="main",
                use_storage=True,
                storage_allowed_paths=["/data"],
                org_id=5,
                # Missing storage_org_prefix
            )

    def test_validator_accepts_complete_storage_scope(self):
        """CodeTaskData should accept complete storage scope."""
        task = CodeTaskData(
            venv_name="test-venv",
            libraries=["requests"],
            code="print('hello')",
            execution_id="exec-123",
            entrypoint="main",
            use_storage=True,
            storage_allowed_paths=["/data"],
            storage_org_prefix="org_42",
            org_id=5,
        )
        assert task.use_storage is True


class TestFileExtractorNodeData:
    """Tests for FileExtractorNodeData with use_storage."""

    def test_use_storage_defaults_to_true(self):
        """FileExtractorNodeData should have use_storage=True by default."""
        node = FileExtractorNodeData(
            node_name="file-extractor-1",
            input_map={"file": "input_file"},
        )
        assert node.use_storage is True

    def test_has_scope_fields(self):
        """FileExtractorNodeData should have storage scope fields."""
        node = FileExtractorNodeData(
            node_name="file-extractor-1",
            input_map={"file": "input_file"},
            storage_allowed_paths=["/data"],
            storage_org_prefix="org_42",
            session_id=10,
            org_id=3,
        )
        assert node.storage_allowed_paths == ["/data"]
        assert node.storage_org_prefix == "org_42"
        assert node.session_id == 10
        assert node.org_id == 3


class TestAudioTranscriptionNodeData:
    """Tests for AudioTranscriptionNodeData with use_storage."""

    def test_use_storage_defaults_to_true(self):
        """AudioTranscriptionNodeData should have use_storage=True by default."""
        node = AudioTranscriptionNodeData(
            node_name="audio-transcription-1",
            input_map={"audio": "input_audio"},
        )
        assert node.use_storage is True

    def test_has_scope_fields(self):
        """AudioTranscriptionNodeData should have storage scope fields."""
        node = AudioTranscriptionNodeData(
            node_name="audio-transcription-1",
            input_map={"audio": "input_audio"},
            storage_allowed_paths=["/audio"],
            storage_org_prefix="org_99",
            session_id=20,
            org_id=4,
        )
        assert node.storage_allowed_paths == ["/audio"]
        assert node.storage_org_prefix == "org_99"
        assert node.session_id == 20
        assert node.org_id == 4
