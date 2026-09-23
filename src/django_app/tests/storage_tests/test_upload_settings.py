from django.conf import settings

from django_app.spectacular_hooks import add_stream_upload_postprocessing_hook
from tables.constants.storage_constants import UPLOAD_STREAM_PATH


def test_new_settings_present():
    assert settings.ORG_STORAGE_QUOTA > 0
    assert settings.MAX_ARCHIVE_FILE_SIZE == 50 * 1024 * 1024
    assert settings.UPLOAD_PART_SIZE >= 5 * 1024 * 1024
    assert settings.UPLOAD_MAX_CONCURRENCY >= 1


def test_stream_upload_is_uncapped_by_default():
    assert settings.MAX_STREAM_UPLOAD_FILE_SIZE is None


def test_stream_endpoint_is_in_the_schema():
    result = add_stream_upload_postprocessing_hook({}, None, None, True)
    operation = result["paths"][UPLOAD_STREAM_PATH]["post"]
    assert operation["requestBody"]["content"]["application/octet-stream"]
    assert {"filename", "path"} == {p["name"] for p in operation["parameters"]}
