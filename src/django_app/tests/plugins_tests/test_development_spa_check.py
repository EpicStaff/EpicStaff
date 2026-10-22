"""The page decision nginx asks for each plugin page request in plugin development mode."""

import pytest
from plugins.development.development_targets import DevelopmentPageDecisionService
from plugins.models import Plugin, PluginDevelopmentTarget, PluginState

from tests.plugins_tests.conftest import DEVELOPMENT_HOST_ADDRESS, GATEWAY_SECRET, mark_running

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root", "page_decisions_in_request_thread"),
]

CHECK_URL = "/api/plugin-gateway/development-spa/"


@pytest.fixture
def page_decisions_in_request_thread(monkeypatch):
    """Run the decision's database work in the test's thread, inside its transaction."""
    monkeypatch.setattr(
        "plugins.gateway.development_spa_check_view._page_decisions",
        DevelopmentPageDecisionService(in_request_thread=True),
    )


@pytest.fixture(autouse=True)
def gateway_secret(settings):
    settings.PLUGINS_GATEWAY_SECRET = GATEWAY_SECRET


@pytest.fixture
def weather(backend_plugin):
    """Weather with a backend and a page, running."""
    return mark_running(backend_plugin())


def _ask(client, identifier="weather", secret=GATEWAY_SECRET):
    headers = {"HTTP_X_PLUGIN_IDENTIFIER": identifier}
    if secret is not None:
        headers["HTTP_X_PLUGIN_GATEWAY_SECRET"] = secret
    return client.get(CHECK_URL, **headers)


def _answer(response):
    return response.status_code, response.headers.get("X-Plugin-Spa-Upstream")


@pytest.mark.parametrize("secret", [None, "", "wrong", GATEWAY_SECRET[:-1]], ids=["missing", "empty", "wrong", "prefix"])
@pytest.mark.usefixtures("development_mode", "development_host_resolves")
def test_without_the_gateway_secret_the_answer_is_an_empty_404(weather, anonymous_client, secret):
    PluginDevelopmentTarget.objects.create(plugin=weather, spa_port=5173)

    response = _ask(anonymous_client, secret=secret)

    assert response.status_code == 404
    assert response.content == b""
    assert "X-Plugin-Spa-Upstream" not in response.headers


@pytest.mark.usefixtures("development_mode", "development_host_resolves")
def test_a_page_port_with_a_resolving_host_is_the_upstream(weather, anonymous_client):
    PluginDevelopmentTarget.objects.create(plugin=weather, spa_port=5173)

    assert _answer(_ask(anonymous_client)) == (403, f"{DEVELOPMENT_HOST_ADDRESS}:5173")


@pytest.mark.usefixtures("development_mode", "development_host_unresolved")
def test_a_page_port_with_an_unresolved_host_has_no_upstream(weather, anonymous_client):
    PluginDevelopmentTarget.objects.create(plugin=weather, spa_port=5173)

    assert _answer(_ask(anonymous_client)) == (403, None)


@pytest.mark.usefixtures("development_host_resolves")
def test_with_the_mode_off_the_published_page_is_served(weather, anonymous_client, development_host_resolves):
    PluginDevelopmentTarget.objects.create(plugin=weather, spa_port=5173)

    assert _answer(_ask(anonymous_client)) == (204, None)
    assert development_host_resolves.calls == []


@pytest.mark.usefixtures("development_mode", "development_host_resolves")
def test_without_a_target_the_published_page_is_served(weather, anonymous_client):
    assert _answer(_ask(anonymous_client)) == (204, None)


@pytest.mark.usefixtures("development_mode", "development_host_resolves")
def test_a_backend_port_alone_leaves_the_published_page(weather, anonymous_client):
    PluginDevelopmentTarget.objects.create(plugin=weather, backend_port=8001)

    assert _answer(_ask(anonymous_client)) == (204, None)


@pytest.mark.parametrize("state", [PluginState.FAILED, PluginState.MAINTENANCE, PluginState.UNINSTALLING])
@pytest.mark.usefixtures("development_mode", "development_host_resolves")
def test_a_plugin_that_is_not_running_serves_its_published_page(weather, anonymous_client, state):
    PluginDevelopmentTarget.objects.create(plugin=weather, spa_port=5173)
    Plugin.objects.filter(pk=weather.pk).update(state=state)

    assert _answer(_ask(anonymous_client)) == (204, None)


@pytest.mark.usefixtures("development_mode", "development_host_resolves")
def test_a_package_without_a_page_is_never_rerouted(weather, anonymous_client):
    PluginDevelopmentTarget.objects.create(plugin=weather, spa_port=5173)
    package = weather.current_package
    package.manifest = {key: value for key, value in package.manifest.items() if key != "spa"}
    package.save(update_fields=["manifest"])

    assert _answer(_ask(anonymous_client)) == (204, None)


@pytest.mark.usefixtures("development_mode", "development_host_resolves")
def test_only_the_named_plugin_s_target_answers(weather, running_plugin, anonymous_client):
    radar = running_plugin(id="radar")
    PluginDevelopmentTarget.objects.create(plugin=radar, spa_port=5174)

    assert _answer(_ask(anonymous_client, "weather")) == (204, None)
    assert _answer(_ask(anonymous_client, "radar")) == (403, f"{DEVELOPMENT_HOST_ADDRESS}:5174")
    assert _answer(_ask(anonymous_client, "unknown")) == (204, None)


@pytest.mark.usefixtures("development_mode", "development_host_resolves")
def test_a_write_reroutes_this_process_at_once(weather, anonymous_client, superadmin_client, django_capture_on_commit_callbacks):
    before = _answer(_ask(anonymous_client))

    with django_capture_on_commit_callbacks(execute=True):
        superadmin_client.put("/api/admin/plugins/weather/development/", {"spa_port": 5173}, format="json")
    during = _answer(_ask(anonymous_client))
    with django_capture_on_commit_callbacks(execute=True):
        superadmin_client.delete("/api/admin/plugins/weather/development/")
    after = _answer(_ask(anonymous_client))

    assert (before, during, after) == ((204, None), (403, f"{DEVELOPMENT_HOST_ADDRESS}:5173"), (204, None))


@pytest.mark.usefixtures("development_mode", "development_host_resolves")
def test_a_repeated_decision_is_answered_from_the_cache(weather, anonymous_client, django_assert_num_queries):
    PluginDevelopmentTarget.objects.create(plugin=weather, spa_port=5173)
    _ask(anonymous_client)

    with django_assert_num_queries(0):
        assert _answer(_ask(anonymous_client))[0] == 403


@pytest.mark.usefixtures("development_mode", "development_host_resolves")
def test_turning_the_mode_off_serves_the_published_page_at_once(weather, anonymous_client, settings):
    PluginDevelopmentTarget.objects.create(plugin=weather, spa_port=5173)
    assert _answer(_ask(anonymous_client))[0] == 403

    settings.PLUGINS_DEV_MODE = False

    assert _answer(_ask(anonymous_client)) == (204, None)


def test_the_decision_runs_in_a_worker_thread_off_the_event_loop(anonymous_client, monkeypatch):
    monkeypatch.setattr(
        "plugins.gateway.development_spa_check_view._page_decisions", DevelopmentPageDecisionService()
    )

    assert _ask(anonymous_client, secret="wrong").status_code == 404
