"""`target_path` composes and validates the destination of an upload.

The whole destination path is name-checked, same as mkdir/rename/move/copy.
"""

import pytest
from rest_framework.exceptions import ValidationError

from tables.services.storage_service.upload.target import clean_folder, target_path
from tables.validators.file_upload_validator import FileValidator

LEGACY_FOLDER = "in\x07box"
ORG_ID = 1  # only used to build a storage key prefix; no row is read


@pytest.fixture
def validator():
    return FileValidator()


class TestUploadDestinationFolder:
    def test_a_clean_folder_becomes_the_target_prefix(self, validator):
        assert target_path(ORG_ID, "docs/reports", "x.txt", validator) == "docs/reports/x.txt"

    def test_the_storage_root_is_a_valid_destination(self, validator):
        assert target_path(ORG_ID, "", "clean.txt", validator) == "clean.txt"

    def test_uploading_into_a_control_character_folder_is_refused(self, validator):
        with pytest.raises(ValidationError) as error:
            target_path(ORG_ID, LEGACY_FOLDER, "clean.txt", validator)

        assert "control character" in str(error.value.detail["path"])

    def test_uploading_into_a_clean_subfolder_of_a_legacy_folder_is_refused(self, validator):
        with pytest.raises(ValidationError) as error:
            target_path(ORG_ID, f"{LEGACY_FOLDER}/sub", "clean.txt", validator)

        assert "control character" in str(error.value.detail["path"])

    def test_a_control_character_in_the_file_name_is_refused(self, validator):
        with pytest.raises(ValidationError) as error:
            target_path(ORG_ID, "docs", "bad\nname.txt", validator)

        assert "control character" in str(error.value.detail["filename"])

    def test_a_path_separator_in_the_file_name_is_refused(self, validator):
        with pytest.raises(ValidationError) as error:
            target_path(ORG_ID, "docs", "sub/name.txt", validator)

        assert "path separator" in str(error.value.detail["filename"])

    def test_clean_folder_refuses_a_destination_outside_the_org_root(self):
        with pytest.raises(ValidationError) as error:
            clean_folder("../other-org")

        assert "escapes the target folder" in str(error.value.detail["path"])
