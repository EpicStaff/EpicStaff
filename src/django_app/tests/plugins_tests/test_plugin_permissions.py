import pytest

from plugins.models import Plugin
from plugins.resource_types import RBAC_RESOURCE_TYPES, PluginResourceType
from rbac.access.builtin_roles import BuiltInRoleSeeder
from rbac.access.catalog import RECOMMENDED_WITH, grantable_bits_for
from rbac.models import Role, RolePermission
from rbac.models.enums import BuiltInRole, Permission, ResourceType
from tables.models import Graph, Secret
from tests.plugins_tests.helpers import (
    INSPECT_URL,
    INSTALL_URL,
    PLUGINS_URL,
    install_payload,
    registered_ids,
    upload,
)

ALL_PLUGIN_ACTIONS = (
    Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE | Permission.USE
)


def test_catalog_grants_crud_and_use_on_plugins():
    assert grantable_bits_for(ResourceType.PLUGINS.value) == ALL_PLUGIN_ACTIONS


@pytest.mark.django_db
def test_only_org_admin_gets_plugins_from_the_seeded_builtin_roles():
    BuiltInRoleSeeder().seed()

    masks = {
        row.role.name: row.permissions
        for row in RolePermission.objects.filter(
            resource_type=ResourceType.PLUGINS.value,
            role__is_built_in=True,
            role__org__isnull=True,
        ).select_related("role")
    }

    assert masks == {BuiltInRole.ORG_ADMIN: int(ALL_PLUGIN_ACTIONS)}


@pytest.mark.django_db
@pytest.mark.parametrize("role_fixture", ["role_member", "role_viewer"])
def test_member_and_viewer_cannot_install_inspect_or_list(
    request, role_fixture, acme, member_of, org_client, sample_zip
):
    user = member_of(acme, request.getfixturevalue(role_fixture), f"{role_fixture}@acme.test")
    client = org_client(user, acme)

    install = client.post(INSTALL_URL, install_payload(sample_zip), format="multipart")
    inspect = client.post(INSPECT_URL, {"file": upload(sample_zip)}, format="multipart")
    listing = client.get(PLUGINS_URL)

    assert install.status_code == 403
    assert inspect.status_code == 403
    assert listing.status_code == 403
    assert not Plugin.objects.exists()


@pytest.fixture
def plugins_only_client(acme, member_of, org_client):
    """Every plugins action, and nothing on the types a plugin bundles."""
    role = Role.objects.create(name="Plugin installer", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.PLUGINS.value, permissions=int(ALL_PLUGIN_ACTIONS)
    )
    yield org_client(member_of(acme, role, "installer@acme.test"), acme)


@pytest.mark.django_db
def test_install_needs_create_on_every_contained_type(
    plugins_only_client, openai_catalog, storage_backend, sample_zip
):
    response = plugins_only_client.post(INSTALL_URL, install_payload(sample_zip), format="multipart")

    assert response.status_code == 403, response.content
    body = response.json()
    assert body["code"] == "plugin_install_forbidden"
    assert {item["resource_type"] for item in body["errors"]} == {
        "flows",
        "agents",
        "surfaces",
        "llm_configs",
        "secrets",
        "knowledge_sources",
        "files",
    }
    assert not Plugin.objects.exists()
    assert not Graph.objects.exists()
    assert not Secret.objects.exists()
    assert storage_backend._objects == {}


@pytest.mark.django_db
def test_inspect_reports_missing_permissions_without_refusing(plugins_only_client, sample_zip):
    response = plugins_only_client.post(INSPECT_URL, {"file": upload(sample_zip)}, format="multipart")

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["can_install"] is False
    assert {"resource_type": "secrets", "action": "create"} in body["missing_permissions"]


@pytest.fixture
def acme_plugin(acme):
    yield Plugin.objects.create(
        org=acme, plugin_id="chat-bot", version="0.1.0", format_version=1, bridge_version=1, name="Chat Bot"
    )


@pytest.mark.django_db
def test_another_org_gets_404_for_a_plugin_and_never_lists_it(
    acme_plugin, beta, role_org_admin, member_of, org_client
):
    beta_admin = member_of(beta, role_org_admin, "admin@beta.test")
    client = org_client(beta_admin, beta)

    assert client.get(f"{PLUGINS_URL}{acme_plugin.pk}/").status_code == 404
    listing = client.get(PLUGINS_URL)
    assert listing.status_code == 200
    assert listing.json() == []


@pytest.mark.django_db
def test_org_admin_sees_its_own_plugin(acme_plugin, admin_client):
    response = admin_client.get(f"{PLUGINS_URL}{acme_plugin.pk}/")

    assert response.status_code == 200
    assert response.json()["plugin_id"] == "chat-bot"


LIFECYCLE_ACTIONS = [
    ("post", "suspend/"),
    ("post", "resume/"),
    ("post", "retry/"),
    ("post", "secrets/"),
    ("get", "delete-preview/"),
    ("delete", ""),
    ("post", "ui-session/"),
]


@pytest.mark.django_db
@pytest.mark.parametrize("role_fixture", ["role_member", "role_viewer"])
@pytest.mark.parametrize("method, suffix", LIFECYCLE_ACTIONS)
def test_member_and_viewer_cannot_run_lifecycle_actions(
    request, role_fixture, method, suffix, acme_plugin, acme, member_of, org_client
):
    user = member_of(acme, request.getfixturevalue(role_fixture), f"{role_fixture}@acme.test")

    response = getattr(org_client(user, acme), method)(
        f"{PLUGINS_URL}{acme_plugin.pk}/{suffix}", {}, format="json"
    )

    assert response.status_code == 403, response.content
    assert Plugin.objects.filter(pk=acme_plugin.pk, suspended=False).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("method, suffix", LIFECYCLE_ACTIONS)
def test_org_admin_passes_the_permission_gate_of_lifecycle_actions(
    method, suffix, acme_plugin, admin_client, stopped_sessions
):
    response = getattr(admin_client, method)(
        f"{PLUGINS_URL}{acme_plugin.pk}/{suffix}", {}, format="json"
    )

    # A domain refusal (409 not ready / 400 no secrets) is fine; a 403 is not.
    assert response.status_code not in (401, 403, 404), response.content


@pytest.mark.django_db
@pytest.mark.parametrize("method, suffix", LIFECYCLE_ACTIONS)
def test_lifecycle_actions_on_another_orgs_plugin_are_404(
    method, suffix, acme_plugin, beta, role_org_admin, member_of, org_client
):
    client = org_client(member_of(beta, role_org_admin, "admin@beta.test"), beta)

    response = getattr(client, method)(f"{PLUGINS_URL}{acme_plugin.pk}/{suffix}", {}, format="json")

    assert response.status_code == 404, response.content
    assert Plugin.objects.filter(pk=acme_plugin.pk, suspended=False).exists()


# --- uninstall needs delete on what it removes --------------------------------------

SAMPLE_RBAC_TYPES = (
    "agents",
    "files",
    "flows",
    "knowledge_sources",
    "llm_configs",
    "secrets",
    "surfaces",
)


@pytest.fixture
def remover_without_flows_delete(acme, member_of, org_client):
    """Every plugins action and delete on every type the sample installs, except flows."""
    role = Role.objects.create(name="Plugin remover", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.PLUGINS.value, permissions=int(ALL_PLUGIN_ACTIONS)
    )
    for resource_type in SAMPLE_RBAC_TYPES:
        if resource_type != "flows":
            RolePermission.objects.create(
                role=role,
                resource_type=resource_type,
                permissions=int(Permission.READ | Permission.DELETE),
            )
    yield org_client(member_of(acme, role, "remover@acme.test"), acme)


@pytest.mark.django_db
def test_delete_without_delete_on_a_contained_type_is_refused_and_deletes_nothing(
    installed_plugin, remover_without_flows_delete, storage_backend, stopped_sessions
):
    graph_ids = registered_ids(installed_plugin, "flow")
    secret_ids = registered_ids(installed_plugin, "secret")
    stored_keys = set(storage_backend._objects)

    response = remover_without_flows_delete.delete(f"{PLUGINS_URL}{installed_plugin.pk}/")

    assert response.status_code == 403, response.content
    body = response.json()
    assert body["code"] == "plugin_delete_forbidden"
    assert body["errors"] == [{"resource_type": "flows", "action": "delete"}]
    assert Plugin.objects.filter(pk=installed_plugin.pk, suspended=False).exists()
    assert Graph.objects.filter(pk__in=graph_ids).count() == len(graph_ids)
    assert Secret.objects.filter(pk__in=secret_ids).count() == len(secret_ids)
    assert set(storage_backend._objects) == stored_keys


@pytest.mark.django_db
def test_delete_preview_lists_the_delete_permissions_the_caller_lacks(
    installed_plugin, plugins_only_client, remover_without_flows_delete
):
    plugins_only = plugins_only_client.get(f"{PLUGINS_URL}{installed_plugin.pk}/delete-preview/")
    remover = remover_without_flows_delete.get(f"{PLUGINS_URL}{installed_plugin.pk}/delete-preview/")

    assert plugins_only.status_code == 200, plugins_only.content
    assert plugins_only.json()["missing_permissions"] == [
        {"resource_type": resource_type, "action": "delete"} for resource_type in SAMPLE_RBAC_TYPES
    ]
    assert remover.json()["missing_permissions"] == [{"resource_type": "flows", "action": "delete"}]


@pytest.mark.django_db
def test_org_admin_has_every_delete_permission_and_deletes(
    installed_plugin, admin_client, storage_backend, stopped_sessions
):
    preview = admin_client.get(f"{PLUGINS_URL}{installed_plugin.pk}/delete-preview/")
    response = admin_client.delete(f"{PLUGINS_URL}{installed_plugin.pk}/")

    assert preview.json()["missing_permissions"] == []
    assert response.status_code == 204, response.content
    assert not Plugin.objects.exists()
    assert not Graph.objects.exists()


@pytest.mark.django_db
def test_a_type_the_org_already_deleted_needs_no_delete_permission(
    installed_plugin, remover_without_flows_delete, storage_backend, stopped_sessions
):
    Graph.objects.filter(pk__in=registered_ids(installed_plugin, "flow")).delete()

    preview = remover_without_flows_delete.get(f"{PLUGINS_URL}{installed_plugin.pk}/delete-preview/")
    response = remover_without_flows_delete.delete(f"{PLUGINS_URL}{installed_plugin.pk}/")

    assert preview.json()["missing_permissions"] == []
    assert response.status_code == 204, response.content
    assert not Plugin.objects.exists()


@pytest.mark.parametrize("resource_type", list(PluginResourceType))
def test_every_plugin_resource_type_is_gated_by_an_rbac_type_with_create_and_delete(resource_type):
    rbac_type = RBAC_RESOURCE_TYPES[resource_type]
    bits = grantable_bits_for(rbac_type.value)

    assert bits & Permission.CREATE
    assert bits & Permission.DELETE


@pytest.mark.parametrize("action", ["create", "delete"])
def test_plugins_install_and_delete_recommend_the_action_on_every_contained_type(action):
    recommended = set(RECOMMENDED_WITH[ResourceType.PLUGINS.value][action])

    for rbac_type in set(RBAC_RESOURCE_TYPES.values()):
        assert (rbac_type.value, action) in recommended, f"plugins:{action} misses {rbac_type.value}:{action}"
