"""A plugin ships a key-value table: install, conflicts, permissions, manifest rules, access."""

import pytest

from plugins.exceptions import InvalidPluginError
from plugins.manifest import load_package
from plugins.models import Plugin, PluginResource
from plugins.samples.zip_builder import build_zip
from plugins.services.bundle_reader import read_bundle
from rbac.models import Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.models import Graph, KeyValueNode, KeyValueTable, Secret
from tables.services.key_value_table_service import KeyValueTableService
from tests.plugins_tests.helpers import (
    INSPECT_URL,
    INSTALL_URL,
    chat_admin_files,
    install_payload,
    plugin_url,
    registered_ids,
    upload,
)

TABLE_NAME = "chat_admin__conversations"


def _install(client, content: bytes):
    return client.post(INSTALL_URL, install_payload(content), format="multipart")


def _load(resources: dict, manifest: dict):
    return load_package(read_bundle(upload(build_zip(chat_admin_files(resources, manifest)))))


def _errors(resources: dict, manifest: dict) -> list[str]:
    with pytest.raises(InvalidPluginError) as caught:
        _load(resources, manifest)
    return [error["message"] for error in caught.value.errors]


def _key_value_nodes(resources: dict) -> list[dict]:
    return [
        node
        for node in resources["Flow"][0]["nodes"]
        if node["node_type"] == "KeyValueNode"
    ]


# --- install ------------------------------------------------------------------------


@pytest.mark.django_db
def test_install_creates_a_prefixed_table_and_binds_the_flows_nodes_to_it(
    admin_client, acme, chat_admin_zip, chat_admin_bundle
):
    own = KeyValueTable.objects.create(org=acme, name="conversations")
    _, _, refs = chat_admin_bundle

    response = _install(admin_client, chat_admin_zip)

    assert response.status_code == 201, response.content
    plugin = Plugin.objects.get(org=acme, plugin_id="chat-admin")
    table = KeyValueTable.objects.get(org=acme, name=TABLE_NAME)
    assert table.description == "One entry per chat conversation."
    assert table.pk != own.pk
    assert list(
        PluginResource.objects.filter(plugin=plugin, resource_type="key_value_table").values_list(
            "object_id", "manifest_ref"
        )
    ) == [(table.pk, str(refs["KeyValueTable"]))]
    [flow_id] = registered_ids(plugin, "flow")
    nodes = KeyValueNode.objects.filter(graph_id=flow_id)
    assert sorted(nodes.values_list("mode", flat=True)) == ["read", "write"]
    assert set(nodes.values_list("key_value_table_id", flat=True)) == {table.pk}
    assert not own.nodes.exists()
    assert response.json()["contents"]["key_value_table"] == 1


@pytest.mark.django_db
def test_a_table_name_the_org_already_has_in_any_case_is_a_409_conflict(
    admin_client, acme, chat_admin_zip
):
    KeyValueTable.objects.create(org=acme, name="CHAT_ADMIN__CONVERSATIONS")

    response = _install(admin_client, chat_admin_zip)

    assert response.status_code == 409, response.content
    assert response.json()["code"] == "plugin_resource_conflict"
    assert response.json()["errors"] == [
        {
            "type": "key_value_table",
            "name": TABLE_NAME,
            "message": f"A key-value table named '{TABLE_NAME}' already exists.",
        }
    ]
    assert not Plugin.objects.exists()
    assert not Graph.objects.filter(org=acme).exists()


@pytest.fixture
def installer_with_table_bits(acme, member_of, org_client):
    """Factory -> a client that may install the chat-admin sample, except for some key_value_tables bits."""

    def _make(table_bits: int):
        role = Role.objects.create(name=f"Installer {table_bits}", org=acme, is_built_in=False)
        RolePermission.objects.create(
            role=role, resource_type=ResourceType.PLUGINS.value, permissions=255
        )
        for resource_type in ("flows", "agents", "llm_configs", "secrets"):
            RolePermission.objects.create(
                role=role,
                resource_type=resource_type,
                permissions=int(Permission.CREATE | Permission.READ),
            )
        if table_bits:
            RolePermission.objects.create(
                role=role, resource_type=ResourceType.KEY_VALUE_TABLES.value, permissions=table_bits
            )
        return org_client(member_of(acme, role, f"installer-{table_bits}@acme.test"), acme)

    yield _make


@pytest.mark.django_db
@pytest.mark.parametrize(
    "table_bits, missing",
    [
        (0, ["create", "read", "update"]),
        (int(Permission.CREATE | Permission.READ), ["update"]),
        (int(Permission.READ | Permission.UPDATE), ["create"]),
    ],
    ids=["none", "no-update", "no-create"],
)
def test_install_needs_table_create_and_every_bundled_node_mode_before_any_write(
    installer_with_table_bits, acme, chat_admin_zip, table_bits, missing
):
    client = installer_with_table_bits(table_bits)

    response = _install(client, chat_admin_zip)
    preview = client.post(INSPECT_URL, {"file": upload(chat_admin_zip)}, format="multipart")

    assert response.status_code == 403, response.content
    assert response.json()["code"] == "plugin_install_forbidden"
    expected = [{"resource_type": "key_value_tables", "action": action} for action in missing]
    assert response.json()["errors"] == expected
    assert preview.json()["missing_permissions"] == expected
    assert preview.json()["can_install"] is False
    assert not Plugin.objects.exists()
    assert not Graph.objects.filter(org=acme).exists()
    assert not KeyValueTable.objects.filter(org=acme).exists()
    assert not Secret.objects.filter(org=acme).exists()


@pytest.mark.django_db
def test_install_with_every_table_permission_goes_through(installer_with_table_bits, acme, chat_admin_zip):
    client = installer_with_table_bits(int(Permission.CREATE | Permission.READ | Permission.UPDATE))

    response = _install(client, chat_admin_zip)

    assert response.status_code == 201, response.content
    assert KeyValueTable.objects.filter(org=acme, name=TABLE_NAME).exists()


# --- inspect ------------------------------------------------------------------------


@pytest.mark.django_db
def test_inspect_lists_the_table_its_access_and_a_conflict(
    admin_client, acme, chat_admin_zip, chat_admin_bundle
):
    _, _, refs = chat_admin_bundle
    KeyValueTable.objects.create(org=acme, name=TABLE_NAME)

    body = admin_client.post(INSPECT_URL, {"file": upload(chat_admin_zip)}, format="multipart").json()

    assert {"type": "key_value_table", "ref": str(refs["KeyValueTable"]), "name": TABLE_NAME} in body[
        "contents"
    ]
    assert body["content_counts"]["key_value_table"] == 1
    assert body["access"] == [
        {
            "alias": "chat",
            "type": "flow",
            "ref": refs["Flow"],
            "resource_name": "Chat Admin",
            "actions": ["run", "sessions.read", "sessions.stop"],
        },
        {
            "alias": "conversations",
            "type": "key_value_table",
            "ref": refs["KeyValueTable"],
            "resource_name": TABLE_NAME,
            "actions": ["read"],
        },
    ]
    assert body["plugin"]["bridge_version"] == 2
    assert [conflict["type"] for conflict in body["conflicts"]] == ["key_value_table"]
    assert body["can_install"] is False


# --- manifest rules -----------------------------------------------------------------


@pytest.mark.django_db
def test_the_sample_loads_with_its_tables_renamed_everywhere(chat_admin_bundle):
    resources, manifest, refs = chat_admin_bundle

    package = _load(resources, manifest)

    assert package.entities("KeyValueTable") == [
        {
            "id": refs["KeyValueTable"],
            "name": TABLE_NAME,
            "description": "One entry per chat conversation.",
        }
    ]
    assert {node["key_value_table_name"] for node in _key_value_nodes(package.resources)} == {
        TABLE_NAME
    }


@pytest.mark.django_db
def test_table_access_needs_bridge_2(chat_admin_bundle):
    resources, manifest, _ = chat_admin_bundle

    errors = _errors(resources, {**manifest, "bridge": 1})

    assert any("needs bridge 2 or later" in message for message in errors), errors


@pytest.mark.django_db
@pytest.mark.parametrize(
    "access, message",
    [
        (
            {"alias": "conversations", "type": "key_value_table", "actions": ["run"]},
            "action 'run' does not apply to a key_value_table (allowed: read)",
        ),
        (
            {"alias": "chat", "type": "flow", "actions": ["read"]},
            "action 'read' does not apply to a flow",
        ),
    ],
    ids=["run-on-a-table", "read-on-a-flow"],
)
def test_an_action_must_fit_the_access_type(chat_admin_bundle, access, message):
    resources, manifest, refs = chat_admin_bundle
    ref = refs["KeyValueTable"] if access["type"] == "key_value_table" else refs["Flow"]

    errors = _errors(resources, {**manifest, "access": [{**access, "ref": ref}]})

    assert any(message in error for error in errors), errors


@pytest.mark.django_db
def test_a_table_ref_must_name_a_bundled_table(chat_admin_bundle):
    resources, manifest, refs = chat_admin_bundle
    access = [
        {"alias": "conversations", "type": "key_value_table", "ref": refs["Flow"], "actions": ["read"]}
    ]

    errors = _errors(resources, {**manifest, "access": access})

    assert f"resources.json has no KeyValueTable with id {refs['Flow']}." in errors


@pytest.mark.django_db
@pytest.mark.parametrize(
    "point_node_at",
    [
        {"key_value_table": None, "key_value_table_name": "customers"},
        {"key_value_table": 987654, "key_value_table_name": "customers"},
    ],
    ids=["by-name-only", "by-an-unshipped-id"],
)
def test_a_node_may_not_use_a_table_the_plugin_does_not_ship(chat_admin_bundle, point_node_at):
    """Otherwise the import would bind it by name to the installing org's own table."""
    resources, manifest, _ = chat_admin_bundle
    _key_value_nodes(resources)[0].update(point_node_at)

    errors = _errors(resources, manifest)

    assert "A Key-Value node may only use a key-value table the plugin ships in resources.json." in errors


@pytest.mark.django_db
def test_a_node_with_no_table_at_all_is_allowed(chat_admin_bundle):
    resources, manifest, _ = chat_admin_bundle
    _key_value_nodes(resources)[0].update({"key_value_table": None, "key_value_table_name": None})

    _load(resources, manifest)


@pytest.mark.django_db
def test_without_the_table_entity_every_bound_node_is_rejected(chat_admin_bundle):
    resources, manifest, refs = chat_admin_bundle
    del resources["KeyValueTable"]
    manifest = {**manifest, "access": manifest["access"][:1]}

    errors = _errors(resources, manifest)

    assert errors.count(
        "A Key-Value node may only use a key-value table the plugin ships in resources.json."
    ) == 2


@pytest.mark.django_db
@pytest.mark.parametrize("extra, valid", [(0, True), (1, False)], ids=["at-limit", "over-limit"])
def test_the_prefixed_table_name_must_fit_255_characters(chat_admin_bundle, extra, valid):
    resources, manifest, _ = chat_admin_bundle
    resources["KeyValueTable"][0]["name"] = "x" * (255 - len("chat_admin__") + extra)

    if valid:
        assert len(_load(resources, manifest).entities("KeyValueTable")[0]["name"]) == 255
    else:
        assert any("is longer than 255 characters" in message for message in _errors(resources, manifest))


@pytest.mark.django_db
def test_two_bundled_tables_may_not_share_a_name_in_any_case(chat_admin_bundle):
    resources, manifest, _ = chat_admin_bundle
    resources["KeyValueTable"].append({"id": 424242, "name": "CONVERSATIONS", "description": ""})

    assert "Two key-value tables are named 'CONVERSATIONS'." in _errors(resources, manifest)


# --- access resolution --------------------------------------------------------------


@pytest.mark.django_db
def test_detail_and_ui_session_resolve_the_table_access(chat_admin_plugin, admin_client, acme):
    table = KeyValueTable.objects.get(org=acme, name=TABLE_NAME)
    [flow_id] = registered_ids(chat_admin_plugin, "flow")

    detail = admin_client.get(plugin_url(chat_admin_plugin)).json()
    session = admin_client.post(plugin_url(chat_admin_plugin, "ui-session")).json()

    assert detail["access"] == [
        {
            "alias": "chat",
            "type": "flow",
            "actions": ["run", "sessions.read", "sessions.stop"],
            "resource_id": flow_id,
            "resource_name": "Chat Admin",
        },
        {
            "alias": "conversations",
            "type": "key_value_table",
            "actions": ["read"],
            "resource_id": table.pk,
            "resource_name": TABLE_NAME,
        },
    ]
    assert session["bridge_version"] == 2
    assert session["access"][1] == {
        "alias": "conversations",
        "type": "key_value_table",
        "actions": ["read"],
        "resource_id": table.pk,
    }


@pytest.mark.django_db
def test_a_table_the_org_deleted_resolves_to_null(chat_admin_plugin, admin_client, acme):
    KeyValueTableService().delete_table(KeyValueTable.objects.get(org=acme, name=TABLE_NAME))

    detail = admin_client.get(plugin_url(chat_admin_plugin)).json()
    session = admin_client.post(plugin_url(chat_admin_plugin, "ui-session")).json()

    assert detail["access"][1]["resource_id"] is None
    assert detail["access"][1]["resource_name"] is None
    assert session["access"][1]["resource_id"] is None
    assert [r["exists"] for r in detail["resources"] if r["type"] == "key_value_table"] == [False]


@pytest.mark.django_db
def test_another_org_never_reaches_the_plugin_or_its_table(
    chat_admin_plugin, acme, beta, role_org_admin, member_of, org_client
):
    table = KeyValueTable.objects.get(org=acme, name=TABLE_NAME)
    client = org_client(member_of(beta, role_org_admin, "admin@beta.test"), beta)

    assert client.get(plugin_url(chat_admin_plugin)).status_code == 404
    assert client.post(plugin_url(chat_admin_plugin, "ui-session")).status_code == 404
    assert client.get(f"/api/key-value-tables/{table.pk}/").status_code == 404
