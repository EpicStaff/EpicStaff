"""The gateway check's database and cache work on worker threads, against a committed database."""

import pytest
from django.core.cache import cache

from tests.plugins_tests.conftest import GATEWAY_SECRET, mark_running

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root"),
]


def test_the_check_answers_from_worker_threads(backend_plugin, anonymous_client, settings):
    settings.PLUGINS_GATEWAY_SECRET = GATEWAY_SECRET
    cache.delete_pattern("plugins:gateway:public-rate:*")
    mark_running(backend_plugin())

    response = anonymous_client.get(
        "/api/plugin-gateway/check/",
        HTTP_X_PLUGIN_GATEWAY_SECRET=GATEWAY_SECRET,
        HTTP_X_PLUGIN_IDENTIFIER="weather",
        HTTP_X_ORIGINAL_METHOD="GET",
        HTTP_X_ORIGINAL_URI="/api/ping",
        HTTP_X_ORIGINAL_NORMALIZED_PATH="/api/ping",
        HTTP_X_REAL_IP="203.0.113.7",
    )

    assert response.status_code == 200
    assert response.headers["X-Plugin-Upstream"] == "es_plugins:20001"
    assert response.headers["X-Plugin-Context"]
