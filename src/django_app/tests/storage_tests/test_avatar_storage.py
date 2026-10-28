"""The configured avatar storage keeps avatars under `system/` and hands out a signed nginx path.

nginx serves `/media/avatars/` from `<bucket>/system/avatars/` only when its
`secure_link` check accepts the `e` and `s` query arguments. The expected signatures come
from nginx's documented recipe, not from the code under test:
`echo -n "<e>/media/<name> <secret>" | openssl md5 -binary | openssl base64 | tr +/ -_ | tr -d =`.
Nothing here reaches the network.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils.module_loading import import_string

from django_app.settings.storage import STORAGES as CONFIGURED_STORAGES

NAME = "avatars/7/0f1e2d3c4b5a69788796a5b4c3d2e1f0.png"


@pytest.mark.parametrize(
    ("now", "expected_query"),
    [
        (1_700_000_000, "e=1700092800&s=jTGbAxBigGTBcfZDqwz9jw"),
        # Exactly at UTC midnight the link still lasts until the end of the next day.
        (1_700_006_400, "e=1700179200&s=Knl-DrQfgirAQva5ear8Jw"),
    ],
)
@override_settings(AVATAR_URL_SIGNING_SECRET="test-signing-secret")
def test_avatar_url_is_the_nginx_media_path_signed_until_the_end_of_the_next_utc_day(
    monkeypatch, now, expected_query
):
    monkeypatch.setattr("rbac.profile.avatar_storage.time.time", lambda: now)
    config = CONFIGURED_STORAGES["avatars"]
    storage = import_string(config["BACKEND"])(**config["OPTIONS"])

    assert storage.location == "system"
    assert storage.url(NAME) == f"/media/{NAME}?{expected_query}"


@pytest.mark.parametrize(
    ("name", "expected_content_type"),
    [
        ("avatars/7/x.png", "image/png"),
        ("avatars/7/x.jpg", "image/jpeg"),
        ("avatars/7/x.html", "application/octet-stream"),
    ],
)
def test_stored_content_type_follows_the_key_not_the_client_content_type(name, expected_content_type):
    config = CONFIGURED_STORAGES["avatars"]
    storage = import_string(config["BACKEND"])(**config["OPTIONS"])
    upload = SimpleUploadedFile("evil.html", b"<html>", content_type="text/html")

    parameters = storage._get_write_parameters(name, upload)

    assert parameters["ContentType"] == expected_content_type
    assert parameters["CacheControl"] == "public, max-age=31536000, immutable"
