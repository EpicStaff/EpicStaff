import io
from importlib import import_module, reload

import pytest
from django.conf import settings as django_settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import clear_url_caches
from django_redis import get_redis_connection
from loguru import logger as loguru_logger
from epicstaff_plugin.signing import generate_secret_key
from plugins.access.declared_access import package_declared_access_bits
from plugins.gateway.gateway_service import snapshot_cache
from plugins.gateway.gateway_service import GatewayDecisionService
from plugins.identity.service_account_keys import ServiceAccountKeyService
from plugins.identity.signing_keys import PluginSigningKeyService, cached_signing_key
from plugins.lifecycle.grant_service import PluginGrantService
from plugins.lifecycle.installation_service import PluginInstallationService
from plugins.ownership import request_scope
from plugins.models import (
    GrantState,
    PlacementHealth,
    PlacementObservedState,
    Plugin,
    PluginGrant,
    PluginNode,
    PluginPlacement,
    PluginDatabaseServer,
    PluginState,
)
from plugins.nodes.node_authentication import node_key_hash
from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from plugins.packages.package_store import PackageFileMissingError
from plugins.packages.spa_publisher import SpaPublisher
from rest_framework.test import APIClient

from tests.plugins_tests.package_builder import GEOCODING_HOST, backend_manifest, build_package, sample_manifest
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


class InMemoryPackageStore:
    """Stands in for the plugin package bucket."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def save(self, key, file):
        self.objects[key] = file.read()

    def download(self, key, destination):
        if key not in self.objects:
            raise PackageFileMissingError(key)
        destination.write(self.objects[key])

    def open(self, key):
        if key not in self.objects:
            raise PackageFileMissingError(key)
        return io.BytesIO(self.objects[key]), len(self.objects[key])

    def delete(self, key):
        self.objects.pop(key, None)


def reload_root_urlconf():
    clear_url_caches()
    reload(import_module(django_settings.ROOT_URLCONF))
    clear_url_caches()


@pytest.fixture
def plugins_enabled(settings):
    """Turn the plugin platform on and mount its routes, as at start-up with the flag set."""
    original = settings.PLUGINS_ENABLED
    settings.PLUGINS_ENABLED = True
    settings.FRONTEND_BASE_URL = "http://epicstaff.localhost"
    settings.PLUGINS_BASE_DOMAIN = "plugins.epicstaff.localhost"
    reload_root_urlconf()
    yield
    settings.PLUGINS_ENABLED = original
    reload_root_urlconf()


@pytest.fixture
def package_store(monkeypatch):
    store = InMemoryPackageStore()
    monkeypatch.setattr("plugins.lifecycle.installation_service.get_package_store", lambda: store)
    monkeypatch.setattr("plugins.lifecycle.upgrade_service.get_package_store", lambda: store)
    monkeypatch.setattr("plugins.views.node_api.get_package_store", lambda: store)
    return store


@pytest.fixture(autouse=True)
def fresh_process_caches():
    """Forget the gateway's plugin snapshots, the cached signing key and declared access bits
    between tests, and any request scope a view called without the middleware left behind."""
    snapshot_cache.clear()
    cached_signing_key.clear()
    package_declared_access_bits.clear()
    token = request_scope._current_scope.set(None)
    yield
    request_scope._current_scope.reset(token)
    snapshot_cache.clear()
    cached_signing_key.clear()
    package_declared_access_bits.clear()


@pytest.fixture
def log_messages():
    """The formatted message of every log record written during the test."""
    messages = []
    sink_id = loguru_logger.add(lambda message: messages.append(message.record["message"]), level="INFO")
    yield messages
    loguru_logger.remove(sink_id)


@pytest.fixture
def spa_root(settings, tmp_path_factory):
    root = tmp_path_factory.mktemp("plugin-spa")
    settings.PLUGINS_SPA_ROOT = root
    return root


@pytest.fixture
def release_key():
    return generate_secret_key()


@pytest.fixture
def trusts_release_key(settings, release_key):
    settings.PLUGINS_TRUSTED_SIGNING_KEYS = [f"release:{release_key.public_key.to_text()}"]
    return release_key


@pytest.fixture
def installation(package_store, spa_root):
    return PluginInstallationService(store=package_store, publisher=SpaPublisher(spa_root))


@pytest.fixture
def anonymous_client():
    return APIClient()


def upload_file(data: bytes, name: str = "weather-0.1.0.esplugin") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, data, content_type="application/octet-stream")


@pytest.fixture
def running_plugin(installation, superadmin, django_capture_on_commit_callbacks):
    """Factory → a plugin uploaded and approved through the real service, so it is running."""

    def _make(**manifest_changes):
        data = build_package(manifest=sample_manifest(**manifest_changes))
        package = installation.upload(upload_file(data), len(data), superadmin)
        with django_capture_on_commit_callbacks(execute=True):
            installation.approve(package.pk, superadmin, untrusted_acknowledged=True)
        return Plugin.objects.get(pk=package.plugin_id)

    return _make


@pytest.fixture
def grant_to(superadmin):
    """Factory → an active grant of `plugin` to `organization`."""

    def _make(plugin, organization, state=GrantState.ACTIVE):
        return PluginGrant.objects.create(plugin=plugin, org=organization, state=state, created_by=superadmin)

    return _make


@pytest.fixture
def make_member(django_user_model):
    """Factory → a user who is a member of `organization` with `role`."""

    def _make(organization, role, email):
        user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
        OrganizationUser.objects.create(user=user, org=organization, role=role)
        return user

    return _make


@pytest.fixture
def make_custom_role():
    """Factory → a custom role of `organization` holding `permissions` ({resource type: actions})."""

    def _make(organization, name, permissions=None):
        role = Role.objects.create(name=name, org=organization, is_built_in=False)
        for resource_type, actions in (permissions or {}).items():
            bits = 0
            for action in actions:
                bits |= int(Permission[action.upper()])
            RolePermission.objects.create(role=role, resource_type=resource_type, permissions=bits)
        return role

    return _make


ROLE_MANAGER_PERMISSIONS = {ResourceType.ROLES.value: ["create", "read", "update", "delete"]}


NODE_KEY = "node-key-" + "k" * 40
GATEWAY_SECRET = "gateway-secret-" + "s" * 40


@pytest.fixture
def plugin_node(db, settings):
    """The deployment's plugin node and the first signing key, as `seed_plugin_node` makes them.

    The gateway secret is set too: nginx's internal listener sends it with every request from
    the plugins network, and plugin credentials are accepted only with it.
    """
    settings.PLUGINS_NODE_NAME = "node-1"
    settings.PLUGINS_GATEWAY_SECRET = GATEWAY_SECRET
    PluginSigningKeyService().ensure_key()
    return PluginNode.objects.create(
        name="node-1",
        key_hash=node_key_hash(NODE_KEY),
        internal_host="es_plugins",
        port_range_start=20001,
        port_range_end=20999,
        uid_range_start=20000,
        uid_range_end=20999,
    )


@pytest.fixture
def node_client():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"PluginNodeKey {NODE_KEY}", HTTP_X_PLUGIN_NETWORK_SECRET=GATEWAY_SECRET)
    return client


@pytest.fixture
def backend_plugin(installation, superadmin, plugin_node, django_capture_on_commit_callbacks):
    """Factory → a plugin with a backend, uploaded and approved: `provisioning`, with a placement."""

    def _make(**manifest_changes):
        data = build_package(manifest=backend_manifest(**manifest_changes))
        package = installation.upload(upload_file(data), len(data), superadmin)
        with django_capture_on_commit_callbacks(execute=True):
            installation.approve(package.pk, superadmin, untrusted_acknowledged=True)
        return Plugin.objects.select_related("placement", "current_package").get(pk=package.plugin_id)

    return _make


@pytest.fixture
def plugin_database_server(db):
    """The plugin database server, as `seed_plugin_node` registers it while plugins are on."""
    return PluginDatabaseServer.objects.create(name="plugins_db", host="plugins_db", port=5432)


@pytest.fixture
def database_plugin(backend_plugin, plugin_database_server):
    """Factory → a plugin with a backend, a database and one outbound host, approved: it has
    its placement and its database record."""

    def _make(**manifest_changes):
        changes = {"database": {}, "outbound_hosts": [dict(GEOCODING_HOST)], **manifest_changes}
        return backend_plugin(**changes)

    return _make


def mark_running(plugin):
    """What the node's first healthy report does: the process runs and the plugin is running."""
    PluginPlacement.objects.filter(plugin=plugin).update(
        observed_state=PlacementObservedState.RUNNING,
        observed_version=plugin.current_package.version,
        health=PlacementHealth.OK,
    )
    Plugin.objects.filter(pk=plugin.pk).update(state=PluginState.RUNNING)
    plugin.refresh_from_db()
    return plugin


OTHER_NODE_KEY = "other-node-key-" + "o" * 40


@pytest.fixture
def other_node(db):
    """A second node, for the checks that one node never sees another's placements."""
    return PluginNode.objects.create(
        name="node-2",
        key_hash=node_key_hash(OTHER_NODE_KEY),
        internal_host="es_plugins_2",
        port_range_start=20001,
        port_range_end=20999,
        uid_range_start=30000,
        uid_range_end=30999,
    )


@pytest.fixture
def other_node_client(other_node):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"PluginNodeKey {OTHER_NODE_KEY}", HTTP_X_PLUGIN_NETWORK_SECRET=GATEWAY_SECRET)
    return client


@pytest.fixture
def gateway_in_request_thread(monkeypatch):
    """Run the gateway check's database work in the test's thread, inside its transaction.

    The check sends that work to worker threads, whose own database connections cannot see
    rows a test creates in its transaction. One test exercises the worker threads for real
    with a committed database.
    """
    monkeypatch.setattr(
        "plugins.gateway.gateway_check_view._decisions",
        GatewayDecisionService(in_request_thread=True),
    )


@pytest.fixture
def clean_login_state():
    """Forget authorization codes, token-exchange throttle counts and the gateway's person cache."""

    def _clean():
        cache.delete_pattern("throttle_plugin_token_*")
        cache.delete_pattern("plugins:gw:person:*")
        connection = get_redis_connection("default")
        codes = connection.keys("plugins:auth_code:*")
        if codes:
            connection.delete(*codes)

    _clean()
    yield
    _clean()


@pytest.fixture
def login_platform(plugins_enabled, package_store, spa_root, clean_login_state, settings):
    """The plugin platform on, over plain http (the refresh cookie is `auth.refresh`)."""
    settings.REFRESH_COOKIE_SECURE = False


@pytest.fixture
def loginable_weather(backend_plugin, login_platform):
    """Weather with a backend, approved and running: people can log in to it."""
    return mark_running(backend_plugin())


# ---- service accounts ----

# What Weather 0.4.0 declares.
WEATHER_ACCESS = [
    {"resource_type": "flows", "actions": ["read", "create", "update", "use"], "reason": "Creates and runs the forecast flow."},
    {"resource_type": "files", "actions": ["read", "create"], "reason": "Stores the readme."},
    {"resource_type": "secrets", "actions": ["read", "create", "use"], "reason": "Stores the LLM key."},
    {"resource_type": "llm_configs", "actions": ["read", "create"], "reason": "Creates the LLM config."},
]


def service_account_client(raw_key, organization=None, *, on_behalf_of=None, network_secret=GATEWAY_SECRET):
    """An API client calling as a plugin backend does: its key, through the internal listener."""
    headers = {"HTTP_AUTHORIZATION": f"PluginKey {raw_key}"}
    if network_secret is not None:
        headers["HTTP_X_PLUGIN_NETWORK_SECRET"] = network_secret
    if organization is not None:
        headers["HTTP_X_ORGANIZATION_ID"] = str(organization.pk)
    if on_behalf_of is not None:
        headers["HTTP_X_EPICSTAFF_ON_BEHALF_OF"] = str(on_behalf_of)
    client = APIClient()
    client.credentials(**headers)
    return client


@pytest.fixture
def service_account_platform(plugins_enabled, package_store, spa_root):
    """The plugin platform on, for service-account calls (the node fixture sets the secret)."""


@pytest.fixture
def weather_backend(backend_plugin, service_account_platform):
    """Factory → Weather with a backend, declaring `access` (Weather 0.4.0's by default), running."""

    def _make(access=None, **manifest_changes):
        return mark_running(backend_plugin(access=WEATHER_ACCESS if access is None else access, **manifest_changes))

    return _make


@pytest.fixture
def service_account_key(superadmin):
    """Factory → a fresh key of `plugin`'s service account in `organization`, granting it first.

    Minted as the node's runtime-credentials call mints them, so every other organization's
    key of the plugin is superseded too.
    """

    def _make(plugin, organization):
        if not PluginGrant.objects.filter(plugin=plugin, org=organization).exists():
            PluginGrantService().grant(plugin.identifier, organization.pk, superadmin)
        minted = ServiceAccountKeyService().mint_for_plugin(plugin)
        return next(key.raw_key for key in minted if key.service_account.grant.org_id == organization.pk)

    return _make


@pytest.fixture
def weather_client(weather_backend, service_account_key, acme):
    """Weather 0.4.0's service account in Acme, as a client without on-behalf-of."""
    plugin = weather_backend()
    return service_account_client(service_account_key(plugin, acme), acme)
