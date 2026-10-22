"""The configured avatar storage keeps avatars under `system/` and hands out the nginx path.

nginx serves `/media/avatars/` from `<bucket>/system/avatars/`, so the URL is the
origin-relative `/media/<name>`. Nothing here reaches the network.
"""

from django.utils.module_loading import import_string

from django_app.settings.storage import STORAGES as CONFIGURED_STORAGES


def test_avatars_live_under_system_and_their_url_is_the_nginx_media_path():
    config = CONFIGURED_STORAGES["avatars"]
    storage = import_string(config["BACKEND"])(**config["OPTIONS"])
    name = "avatars/7/0f1e2d3c4b5a69788796a5b4c3d2e1f0.png"

    assert storage.location == "system"
    assert storage.url(name) == f"/media/{name}"
