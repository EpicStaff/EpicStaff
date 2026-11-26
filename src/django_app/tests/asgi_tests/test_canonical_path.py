"""The path form the ASGI dispatcher looks raw upload apps up by: nginx's own normalisation."""

import pytest

from django_app.asgi import canonical_path, raw_http_apps


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/storage/upload/stream", "/api/storage/upload/stream"),
        ("/api/storage//upload/stream", "/api/storage/upload/stream"),
        ("//api///storage////upload/stream", "/api/storage/upload/stream"),
        ("/api/storage/upload/./stream", "/api/storage/upload/stream"),
        ("/api/./storage/./upload/stream", "/api/storage/upload/stream"),
        ("/api/storage/x/../upload/stream", "/api/storage/upload/stream"),
        ("/api/storage/upload/stream/..", "/api/storage/upload/"),
        ("/api/storage/upload/stream/.", "/api/storage/upload/stream/"),
        ("/../api/storage/upload/stream", "/api/storage/upload/stream"),
        ("/api/graphs/import-jobs/", "/api/graphs/import-jobs/"),
        ("/api//graphs/./import-jobs//", "/api/graphs/import-jobs/"),
        ("/api/graphs/", "/api/graphs/"),
        ("/api/graphs", "/api/graphs"),
        ("/", "/"),
        ("//", "/"),
        ("", "/"),
    ],
)
def test_the_path_is_canonicalised_the_way_nginx_does(path, expected):
    assert canonical_path(path) == expected


def test_a_trailing_slash_decides_whether_an_import_route_matches():
    assert "/api/graphs/import-jobs/" in raw_http_apps
    assert canonical_path("/api/graphs/import-jobs") not in raw_http_apps
