import hashlib
import json

import pytest
from django.db.models import Count
from agents.models import AgentDefinition, Surface, SurfaceKnowledge, SurfaceStorageItem
from agents.models.surface_models import StorageAccess

from plugins.exceptions import InvalidPluginError
from plugins.manifest import load_package
from plugins.models import Plugin, PluginAsset, PluginResource
from plugins.samples.zip_builder import build_sample_zip, build_zip, sample_files
from plugins.services import bundle_reader, install_service, knowledge_service
from plugins.services.bundle_reader import read_bundle
from plugins.services.install_service import PluginInstallService
from tables.models import (
    DocumentMetadata,
    EmbeddingConfig,
    Graph,
    GraphStorageFile,
    LLMConfig,
    Secret,
    SourceCollection,
    StorageFile,
)
from tables.models.knowledge_models import NaiveRag
from tables.services.secrets.encryption import secret_encryption
from tests.plugins_tests.helpers import (
    INSPECT_URL,
    INSTALL_URL,
    PLUGINS_URL,
    SECRETS,
    install_payload,
    upload,
)


def _registered(plugin: Plugin, resource_type: str) -> list[int]:
    return list(
        PluginResource.objects.filter(plugin=plugin, resource_type=resource_type).values_list(
            "object_id", flat=True
        )
    )


@pytest.fixture
def installed(admin_client, openai_catalog, storage_backend, sample_zip):
    response = admin_client.post(INSTALL_URL, install_payload(sample_zip), format="multipart")
    assert response.status_code == 201, response.content
    yield response.json()


# --- happy path -------------------------------------------------------------------


@pytest.mark.django_db
def test_install_creates_and_registers_every_bundled_resource(installed, acme):
    plugin = Plugin.objects.get(org=acme, plugin_id="chat-bot")

    assert plugin.version == "0.1.0"
    assert plugin.state == Plugin.State.PREPARING
    assert plugin.ui_entry == "index.html"
    assert plugin.icon_data_url.startswith("data:image/svg+xml;base64,")
    assert dict(
        PluginResource.objects.filter(plugin=plugin)
        .values_list("resource_type")
        .annotate(count=Count("id"))
    ) == {
        "flow": 1,
        "agent_definition": 1,
        "surface": 1,
        "llm_config": 1,
        "embedding_config": 1,
        "secret": 1,
        "source_collection": 1,
        "storage_file": 1,
    }

    [graph_id] = _registered(plugin, "flow")
    graph = Graph.objects.get(pk=graph_id, org=acme)
    assert graph.name == "Chat Bot"
    [agent_id] = _registered(plugin, "agent_definition")
    agent = AgentDefinition.objects.get(pk=agent_id, organization=acme)
    assert graph.task_node_list.get().agent_definition_id == agent.pk
    [surface_id] = _registered(plugin, "surface")
    assert Surface.objects.get(pk=surface_id).owner_agent_id == agent.pk


@pytest.mark.django_db
def test_install_binds_the_slot_secret_to_the_bundled_configs(installed, acme):
    plugin = Plugin.objects.get(org=acme)
    secret = Secret.objects.get(org=acme)

    assert secret.name == "CHAT_BOT__OPENAI_API_KEY"
    assert secret_encryption.decrypt(encryptedtext=secret.value) == SECRETS["OPENAI_API_KEY"]
    assert _registered(plugin, "secret") == [secret.pk]
    [llm_config_id] = _registered(plugin, "llm_config")
    [embedding_config_id] = _registered(plugin, "embedding_config")
    assert LLMConfig.objects.get(pk=llm_config_id).api_key_secret_id == secret.pk
    assert EmbeddingConfig.objects.get(pk=embedding_config_id).api_key_secret_id == secret.pk


@pytest.mark.django_db
def test_install_creates_the_knowledge_collection_and_attaches_it(installed, acme):
    plugin = Plugin.objects.get(org=acme)
    [collection_id] = _registered(plugin, "source_collection")
    collection = SourceCollection.objects.get(pk=collection_id, org=acme)
    [embedding_config_id] = _registered(plugin, "embedding_config")
    [surface_id] = _registered(plugin, "surface")

    assert collection.collection_name == "Acme Notes knowledge"
    assert sorted(
        DocumentMetadata.objects.filter(source_collection=collection).values_list("file_name", flat=True)
    ) == ["faq.md", "product-overview.md"]
    naive_rag = NaiveRag.objects.get(base_rag_type__source_collection=collection)
    assert naive_rag.embedder_id == embedding_config_id
    assert naive_rag.naive_rag_configs.count() == 2
    knowledge = SurfaceKnowledge.objects.get(surface_id=surface_id)
    assert knowledge.collection_id == collection.pk
    assert knowledge.naive_search_config is not None


@pytest.mark.django_db
def test_install_writes_the_storage_file_and_links_it_to_surface_and_flow(
    installed, acme, storage_backend, sample_zip
):
    plugin = Plugin.objects.get(org=acme)
    storage_file = StorageFile.objects.get(org=acme, path="plugins/chat-bot/tone-guide.md")
    [graph_id] = _registered(plugin, "flow")
    [surface_id] = _registered(plugin, "surface")

    assert storage_backend._objects[f"org_{acme.pk}/plugins/chat-bot/tone-guide.md"][0] == (
        sample_files()["files/tone-guide.md"]
    )
    assert _registered(plugin, "storage_file") == [storage_file.pk]
    item = SurfaceStorageItem.objects.get(surface_id=surface_id, storage_file=storage_file)
    assert item.can_view == StorageAccess.ALLOW
    assert item.can_edit == StorageAccess.UNSET
    assert GraphStorageFile.objects.filter(graph_id=graph_id, storage_file=storage_file).exists()


@pytest.mark.django_db
def test_install_stores_the_ui_files_as_assets(installed, acme):
    files = sample_files()
    assets = {asset.path: asset for asset in PluginAsset.objects.filter(plugin__org=acme)}

    assert set(assets) == {path.removeprefix("ui/") for path in files if path.startswith("ui/")}
    assert bytes(assets["index.html"].content) == files["ui/index.html"]
    assert assets["index.html"].content_type == "text/html; charset=utf-8"
    assert assets["app.js"].content_type == "text/javascript; charset=utf-8"
    assert assets["style.css"].content_type == "text/css; charset=utf-8"
    assert assets["icon.svg"].content_type == "image/svg+xml"
    assert assets["icon.svg"].sha256 == hashlib.sha256(files["ui/icon.svg"]).hexdigest()


@pytest.mark.django_db
def test_install_response_and_list_resolve_access_and_slots(installed, admin_client, acme):
    [graph_id] = _registered(Plugin.objects.get(org=acme), "flow")

    assert installed["status"] == "preparing"
    assert installed["access"] == [
        {
            "alias": "chat",
            "type": "flow",
            "actions": ["run", "sessions.read", "sessions.stop"],
            "resource_id": graph_id,
            "resource_name": "Chat Bot",
        }
    ]
    assert installed["secret_slots"][0]["configured"] is True
    assert installed["secret_slots"][0]["secret_name"] == "CHAT_BOT__OPENAI_API_KEY"
    assert installed["contents"]["flow"] == 1
    assert all(resource["exists"] for resource in installed["resources"])

    listing = admin_client.get(PLUGINS_URL).json()
    assert [plugin["plugin_id"] for plugin in listing] == ["chat-bot"]
    assert "resources" not in listing[0]


@pytest.mark.django_db
def test_a_resource_the_org_deleted_is_reported_as_missing(installed, admin_client, acme):
    Secret.objects.filter(org=acme).delete()

    body = admin_client.get(f"{PLUGINS_URL}{installed['id']}/").json()

    assert body["secret_slots"][0]["configured"] is False
    assert body["secret_slots"][0]["secret_id"] is None
    assert [r["exists"] for r in body["resources"] if r["type"] == "secret"] == [False]


@pytest.mark.django_db
def test_indexing_starts_only_after_the_install_commits(
    monkeypatch, admin_acme, acme, openai_catalog, storage_backend, sample_zip,
    django_capture_on_commit_callbacks,
):
    started = []
    monkeypatch.setattr(knowledge_service, "start_indexing", started.append)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        plugin = PluginInstallService().install(
            upload(sample_zip), secrets=SECRETS, user=admin_acme, org_id=acme.pk
        )
        assert started == []

    for callback in callbacks:
        callback()
    assert started == [plugin.pk]


@pytest.mark.django_db
def test_a_plugin_without_knowledge_is_ready_at_once(
    monkeypatch, admin_acme, acme, openai_catalog, storage_backend, django_capture_on_commit_callbacks
):
    started = []
    monkeypatch.setattr(knowledge_service, "start_indexing", started.append)

    with django_capture_on_commit_callbacks(execute=True):
        plugin = PluginInstallService().install(
            upload(build_sample_zip(manifest_changes={"knowledge": []})),
            secrets=SECRETS,
            user=admin_acme,
            org_id=acme.pk,
        )

    assert plugin.state == Plugin.State.READY
    assert started == []
    assert not SourceCollection.objects.filter(org=acme).exists()


@pytest.mark.django_db
def test_a_zip_of_the_plugin_folder_itself_installs(
    admin_acme, acme, openai_catalog, storage_backend
):
    wrapped = {f"chat-bot/{path}": content for path, content in sample_files().items()}
    wrapped["__MACOSX/chat-bot/._plugin.json"] = b"junk"

    plugin = PluginInstallService().install(
        upload(build_zip(wrapped)), secrets=SECRETS, user=admin_acme, org_id=acme.pk
    )

    assert plugin.plugin_id == "chat-bot"


@pytest.mark.django_db
def test_inspect_previews_without_writing(admin_client, sample_zip):
    response = admin_client.post(INSPECT_URL, {"file": upload(sample_zip)}, format="multipart")

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["plugin"]["plugin_id"] == "chat-bot"
    assert body["can_install"] is True
    assert body["content_counts"] == {
        "flow": 1,
        "agent_definition": 1,
        "surface": 1,
        "llm_config": 1,
        "embedding_config": 1,
        "secret": 1,
        "source_collection": 1,
        "storage_file": 1,
    }
    assert body["access"][0]["resource_name"] == "Chat Bot"
    assert body["secret_slots"][0]["secret_name"] == "CHAT_BOT__OPENAI_API_KEY"
    assert not Plugin.objects.exists()
    assert not Graph.objects.exists()


UI_WARNING_TEXT = (
    "This plugin runs its own code in a sandboxed page. The page can use what is listed below "
    "with the permissions of whoever opens it, and anything it can see could be sent to the "
    "plugin's author."
)
CODE_WARNING_TEXT = (
    "This plugin contains Python code that will run in your organization's sandbox. "
    "Review it before installing."
)


@pytest.mark.django_db
def test_inspect_warns_that_the_page_can_send_what_it_sees_and_omits_the_code_warning_without_code(
    admin_client, sample_zip
):
    body = admin_client.post(INSPECT_URL, {"file": upload(sample_zip)}, format="multipart").json()

    assert body["code_review_items"] == []
    assert body["warnings"][0] == UI_WARNING_TEXT
    assert CODE_WARNING_TEXT not in body["warnings"]


@pytest.mark.django_db
def test_inspect_keeps_the_code_warning_for_a_bundle_with_python_code(admin_client):
    resources = json.loads(sample_files()["resources.json"])
    resources["PythonCodeTool"] = [
        {"id": 3, "name": "Word count", "python_code": {"code": "def main(text):\n    return len(text.split())"}}
    ]
    content = build_sample_zip(replace={"resources.json": json.dumps(resources).encode()})

    body = admin_client.post(INSPECT_URL, {"file": upload(content)}, format="multipart").json()

    assert body["warnings"][:2] == [UI_WARNING_TEXT, CODE_WARNING_TEXT]


# --- all or nothing ---------------------------------------------------------------


@pytest.mark.django_db
def test_a_failure_at_the_asset_step_leaves_nothing_behind(
    monkeypatch, admin_acme, acme, openai_catalog, storage_backend, sample_zip
):
    stored_before_failure = []

    def _fail(self):
        stored_before_failure.extend(storage_backend._objects)
        raise RuntimeError("asset write failed")

    monkeypatch.setattr(install_service._PluginInstallation, "_create_assets", _fail)

    with pytest.raises(RuntimeError, match="asset write failed"):
        PluginInstallService().install(
            upload(sample_zip), secrets=SECRETS, user=admin_acme, org_id=acme.pk
        )

    assert stored_before_failure == [f"org_{acme.pk}/plugins/chat-bot/tone-guide.md"]
    assert not Plugin.objects.exists()
    assert not PluginResource.objects.exists()
    assert not Graph.all_objects.filter(org=acme).exists()
    assert not Secret.objects.filter(org=acme).exists()
    assert not SourceCollection.all_objects.filter(org=acme).exists()
    assert not StorageFile.objects.filter(org=acme).exists()
    assert storage_backend._objects == {}


# --- refusals ---------------------------------------------------------------------


@pytest.mark.django_db
def test_installing_the_same_id_again_is_409(installed, admin_client, sample_zip):
    install = admin_client.post(INSTALL_URL, install_payload(sample_zip), format="multipart")
    inspect = admin_client.post(INSPECT_URL, {"file": upload(sample_zip)}, format="multipart")

    for response in (install, inspect):
        assert response.status_code == 409
        assert response.json()["code"] == "plugin_already_installed"
        assert response.json()["errors"] == [{"plugin_id": "chat-bot", "installed_version": "0.1.0"}]
    assert Plugin.objects.count() == 1


@pytest.mark.django_db
def test_an_identical_llm_config_already_in_the_org_is_not_reused_or_linked(
    admin_client, acme, openai_catalog, storage_backend
):
    """The bundle reads as exported from this very org, so a plain import would
    match the org's own config; the plugin must create and bind its own."""
    resources = json.loads(sample_files()["resources.json"])
    bundled = resources["LLMConfig"][0]
    bundled["org"] = acme.pk
    own = LLMConfig.objects.create(
        model=openai_catalog["llm_model"],
        **{key: value for key, value in bundled.items() if key not in {"id", "model", "tags"}} | {"org": acme},
    )
    content = build_sample_zip(replace={"resources.json": json.dumps(resources).encode()})

    response = admin_client.post(INSTALL_URL, install_payload(content), format="multipart")

    assert response.status_code == 201, response.content
    [plugin_config_id] = _registered(Plugin.objects.get(org=acme), "llm_config")
    assert plugin_config_id != own.pk
    assert LLMConfig.objects.filter(org=acme).count() == 2
    own.refresh_from_db()
    assert own.api_key_secret_id is None
    assert AgentDefinition.objects.get(organization=acme).llm_config_id == plugin_config_id


@pytest.mark.django_db
def test_an_identical_surface_already_in_the_org_is_not_reused(
    admin_client, acme, openai_catalog, storage_backend, sample_zip
):
    bundled = json.loads(sample_files()["resources.json"])["Surface"][0]
    own = Surface.objects.create(
        organization=acme, name=bundled["name"], instructions=bundled["instructions"]
    )

    response = admin_client.post(INSTALL_URL, install_payload(sample_zip), format="multipart")

    assert response.status_code == 201, response.content
    [plugin_surface_id] = _registered(Plugin.objects.get(org=acme), "surface")
    assert plugin_surface_id != own.pk
    assert not SurfaceKnowledge.objects.filter(surface=own).exists()
    assert not SurfaceStorageItem.objects.filter(surface=own).exists()


@pytest.mark.django_db
def test_catalog_models_are_reused_not_copied(installed, acme, openai_catalog):
    [plugin_config_id] = _registered(Plugin.objects.get(org=acme), "llm_config")

    assert LLMConfig.objects.get(pk=plugin_config_id).model_id == openai_catalog["llm_model"].pk
    assert not openai_catalog["llm_model"].__class__.objects.filter(org=acme).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "secrets, problem",
    [
        ({}, "A value is required."),
        ({"OPENAI_API_KEY": "  "}, "The value must not be blank."),
        ({**SECRETS, "OTHER": "x"}, "The plugin has no such secret slot."),
    ],
)
def test_secret_values_must_match_the_slots(admin_client, openai_catalog, sample_zip, secrets, problem):
    response = admin_client.post(INSTALL_URL, install_payload(sample_zip, secrets), format="multipart")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_plugin_secrets"
    assert problem in [error["message"] for error in response.json()["errors"]]
    assert not Plugin.objects.exists()


@pytest.mark.django_db
def test_a_taken_secret_name_is_a_conflict(admin_client, acme, openai_catalog, storage_backend, sample_zip):
    from tables.services.secrets.secret_service import secret_service

    secret_service.create(text="mine", name="CHAT_BOT__OPENAI_API_KEY", org=acme)

    response = admin_client.post(INSTALL_URL, install_payload(sample_zip), format="multipart")

    assert response.status_code == 409
    assert response.json()["code"] == "plugin_resource_conflict"
    assert response.json()["errors"][0]["type"] == "secret"
    assert not Plugin.objects.exists()


@pytest.mark.django_db
def test_a_taken_storage_path_is_a_conflict(admin_client, acme, openai_catalog, storage_backend, sample_zip):
    StorageFile.objects.create(org=acme, path="plugins/chat-bot/tone-guide.md", name="tone-guide.md")

    response = admin_client.post(INSTALL_URL, install_payload(sample_zip), format="multipart")

    assert response.status_code == 409
    assert response.json()["errors"][0]["type"] == "storage_file"
    assert storage_backend._objects == {}


@pytest.mark.django_db
def test_a_slot_carrying_a_value_is_rejected(admin_client, sample_zip):
    content = build_sample_zip(
        manifest_changes={"secret_slots": [{"name": "OPENAI_API_KEY", "value": "sk-leaked"}]}
    )

    response = admin_client.post(INSPECT_URL, {"file": upload(content)}, format="multipart")

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "invalid_plugin"
    assert {"loc": "plugin.json.secret_slots.0.value", "message": "Extra inputs are not permitted"} in body["errors"]


# --- manifest and bundle rules ----------------------------------------------------


def _resources(**changes) -> bytes:
    resources = json.loads(sample_files()["resources.json"])
    resources.update(changes)
    return json.dumps(resources).encode()


def _flow_with_node(node: dict) -> list[dict]:
    flow = json.loads(sample_files()["resources.json"])["Flow"][0]
    flow["nodes"].append(node)
    return [flow]


_SECRET_READING_TOOL = {
    "id": 7,
    "name": "lookup",
    "description": "reads a key",
    "variables": [],
    "built_in": False,
    "use_storage": False,
    "python_code": {
        "code": 'def main():\n    return get_secret("ACME_KEY")',
        "entrypoint": "main",
        "libraries": "",
        "global_kwargs": {},
    },
    "python_code_tool_config": [],
    "labels": [],
}

_BIG_SVG = b"<svg xmlns='http://www.w3.org/2000/svg'>" + b" " * (65 * 1024) + b"</svg>"

MANIFEST_RULES = [
    ("unknown top-level key", {"manifest_changes": {"homepage": "https://x.test"}}, "Extra inputs are not permitted"),
    ("bad id", {"manifest_changes": {"id": "Chat Bot"}}, "String should match pattern"),
    ("bad version", {"manifest_changes": {"version": "latest"}}, "String should match pattern"),
    ("bad slot name", {"manifest_changes": {"secret_slots": [{"name": "openai-key"}], "secret_bindings": []}}, "String should match pattern"),
    ("unsupported format", {"manifest_changes": {"format_version": 2}}, "format_version 2 is not supported"),
    ("unsupported bridge", {"manifest_changes": {"bridge": 3}}, "bridge 3 is not supported"),
    (
        "binding to an undeclared slot",
        {"manifest_changes": {"secret_bindings": [{"entity": "LLMConfig", "ref": 1, "field": "api_key_secret", "slot": "NOPE"}]}},
        "undeclared slot 'NOPE'",
    ),
    (
        "binding through the wrong field",
        {"manifest_changes": {"secret_bindings": [{"entity": "LLMConfig", "ref": 1, "field": "auth_secret", "slot": "OPENAI_API_KEY"}]}},
        "bind through 'api_key_secret'",
    ),
    (
        "duplicate alias",
        {"manifest_changes": {"access": [
            {"alias": "chat", "type": "flow", "ref": 1, "actions": ["run"]},
            {"alias": "chat", "type": "flow", "ref": 1, "actions": ["sessions.read"]},
        ]}},
        "duplicate access alias",
    ),
    (
        "action outside the allowlist",
        {"manifest_changes": {"access": [{"alias": "chat", "type": "flow", "ref": 1, "actions": ["sessions.delete"]}]}},
        "Input should be 'run', 'sessions.read', 'sessions.stop' or 'read'",
    ),
    (
        "access to something other than a flow",
        {"manifest_changes": {"access": [{"alias": "chat", "type": "agent", "ref": 1, "actions": ["run"]}]}},
        "Input should be 'flow' or 'key_value_table'",
    ),
    (
        "ref missing from resources.json",
        {"manifest_changes": {"access": [{"alias": "chat", "type": "flow", "ref": 999, "actions": ["run"]}]}},
        "resources.json has no Flow with id 999",
    ),
    (
        "embedder ref missing from resources.json",
        {"manifest_changes": {"knowledge": [{"name": "k", "embedder": 42, "documents": ["knowledge/faq.md"]}]}},
        "resources.json has no EmbeddingConfig with id 42",
    ),
    ("no plugin.json", {"replace": {"plugin.json": None}}, "The zip has no plugin.json at its root."),
    ("plugin.json not JSON", {"replace": {"plugin.json": b"{nope"}}, "plugin.json is not valid JSON"),
    ("no resources.json", {"replace": {"resources.json": None}}, "The zip has no resources.json at its root."),
    ("resources.json not a flow export", {"replace": {"resources.json": _resources(main_entity="AgentDefinition")}}, "must be a Flow export"),
    ("resources.json from a newer server", {"replace": {"resources.json": _resources(version=99)}}, "newer than supported"),
    ("legacy project entities", {"replace": {"resources.json": _resources(Project=[{"id": 1}])}}, "A plugin cannot contain Project entities."),
    (
        "knowledge node bound to a collection",
        {"replace": {"resources.json": _resources(Flow=_flow_with_node(
            {"id": 50, "node_type": "KnowledgeNode", "node_name": "Search", "source_collection": 3}
        ))}},
        "Knowledge nodes bound to a collection are not supported",
    ),
    (
        "python tool reading a secret by name",
        {"replace": {"resources.json": _resources(PythonCodeTool=[_SECRET_READING_TOOL])}},
        'get_secret("ACME_KEY")',
    ),
    (
        "knowledge document missing",
        {"replace": {"knowledge/faq.md": None}},
        "The zip has no 'knowledge/faq.md'.",
    ),
    (
        "knowledge document outside knowledge/",
        {"manifest_changes": {"knowledge": [{"name": "k", "embedder": 1, "documents": ["files/tone-guide.md"]}]}},
        "must be inside knowledge/",
    ),
    (
        "storage file outside files/",
        {"manifest_changes": {"storage_files": [{"path": "knowledge/faq.md"}]}},
        "must be a file inside files/",
    ),
    ("ui file type not allowed", {"replace": {"ui/app.wasm": b"\0asm"}}, "UI files must be one of"),
    ("ui entry not html", {"manifest_changes": {"ui": {"entry": "ui/icon.svg"}}}, "ui.entry must be an .html file inside ui/."),
    ("icon type not allowed", {"manifest_changes": {"icon": "ui/index.html"}}, "The icon must be a .png or .svg file."),
    ("icon larger than 64 KB", {"replace": {"ui/icon.svg": _BIG_SVG}}, "The icon is larger than 64 KB."),
    ("icon that is not an image", {"replace": {"ui/icon.svg": b"hello"}}, "is not a valid SVG image."),
    ("file outside the known folders", {"replace": {"README.md": b"# hi"}}, "Only plugin.json, resources.json, knowledge/, files/ and ui/"),
    ("executable in the zip", {"replace": {"files/run.sh": b"rm -rf /"}}, "blocked executable extension"),
]


@pytest.mark.parametrize(
    "zip_changes, message",
    [pytest.param(changes, message, id=name) for name, changes, message in MANIFEST_RULES],
)
def test_manifest_and_bundle_rules(zip_changes, message):
    with pytest.raises(InvalidPluginError) as caught:
        load_package(read_bundle(upload(build_sample_zip(**zip_changes))))

    assert any(message in error["message"] for error in caught.value.errors), caught.value.errors


@pytest.mark.parametrize(
    "content, message",
    [
        (b"plain text, not a zip", "A plugin must be a .zip file."),
        (build_zip({"../escape.txt": b"x", **sample_files()}), "escapes the target folder"),
    ],
)
def test_unreadable_or_unsafe_zips_are_rejected(content, message):
    with pytest.raises(InvalidPluginError) as caught:
        read_bundle(upload(content))

    assert message in caught.value.errors[0]["message"]


@pytest.mark.parametrize(
    "limit, value, message",
    [
        ("MAX_BUNDLE_BYTES", 1024, "The file is larger than"),
        ("MAX_BUNDLE_ENTRIES", 3, "more than 3 entries"),
        ("MAX_BUNDLE_UNPACKED_BYTES", 2048, "pushes the extraction past 2048 bytes"),
    ],
)
def test_bundle_caps_are_enforced(monkeypatch, limit, value, message):
    monkeypatch.setattr(bundle_reader, limit, value)

    with pytest.raises(InvalidPluginError) as caught:
        read_bundle(upload(build_sample_zip()))

    assert message in caught.value.errors[0]["message"]


def test_ui_file_count_cap_is_enforced(monkeypatch):
    from plugins import manifest

    monkeypatch.setattr(manifest, "MAX_UI_ASSETS", 1)

    with pytest.raises(InvalidPluginError) as caught:
        load_package(read_bundle(upload(build_sample_zip())))

    assert any("more than 1 files" in error["message"] for error in caught.value.errors)


def _with_ui_files(count: int) -> dict[str, bytes]:
    """The sample with extra one-byte UI files, so ui/ holds `count` files."""
    files = sample_files()
    existing = sum(1 for path in files if path.startswith("ui/"))
    files.update({f"ui/chunk-{index}.js": b"x" for index in range(count - existing)})
    return files


def test_ui_may_hold_300_files():
    package = load_package(read_bundle(upload(build_zip(_with_ui_files(300)))))

    assert len(package.ui_assets) == 300


def test_ui_may_not_hold_301_files():
    with pytest.raises(InvalidPluginError) as caught:
        load_package(read_bundle(upload(build_zip(_with_ui_files(301)))))

    assert {"loc": "ui/", "message": "ui/ holds more than 300 files."} in caught.value.errors


@pytest.mark.parametrize("extra, valid", [(0, True), (1, False)], ids=["20-mb", "20-mb-plus-1"])
def test_ui_may_hold_20_mb(extra, valid):
    files = sample_files()
    used = sum(len(content) for path, content in files.items() if path.startswith("ui/"))
    files["ui/vendor.js"] = b"x" * (20 * 1024 * 1024 - used + extra)
    content = build_zip(files)

    if valid:
        load_package(read_bundle(upload(content)))
    else:
        with pytest.raises(InvalidPluginError) as caught:
            load_package(read_bundle(upload(content)))
        assert {"loc": "ui/", "message": "ui/ is larger than 20 MB."} in caught.value.errors


def test_bundle_caps_leave_room_for_a_framework_build():
    assert bundle_reader.MAX_BUNDLE_BYTES == 30 * 1024 * 1024
    assert bundle_reader.MAX_BUNDLE_ENTRIES == 400
    assert bundle_reader.MAX_BUNDLE_UNPACKED_BYTES == 60 * 1024 * 1024


def test_a_bundle_of_350_entries_is_read():
    files = _with_ui_files(300)
    files.update({f"files/note-{index}.md": b"x" for index in range(350 - len(files))})

    assert len(read_bundle(upload(build_zip(files))).files) == 350


@pytest.mark.parametrize(
    "path, content_type",
    [
        ("ui/chunk-A1.mjs", "text/javascript; charset=utf-8"),
        ("ui/media/inter.woff2", "font/woff2"),
        ("ui/main.js.map", "application/json"),
        ("ui/3rdpartylicenses.txt", "text/plain; charset=utf-8"),
        ("ui/favicon.ico", "image/x-icon"),
    ],
)
def test_framework_build_files_are_accepted_with_their_type(path, content_type):
    package = load_package(read_bundle(upload(build_sample_zip(replace={path: b"x"}))))

    [asset] = [asset for asset in package.ui_assets if asset.path == path.removeprefix("ui/")]
    assert asset.content_type == content_type


def test_every_problem_is_reported_at_once():
    content = build_sample_zip(
        manifest_changes={"access": [{"alias": "chat", "type": "flow", "ref": 999, "actions": ["run"]}]},
        replace={"README.md": b"x", "knowledge/faq.md": None},
    )

    with pytest.raises(InvalidPluginError) as caught:
        load_package(read_bundle(upload(content)))

    assert len(caught.value.errors) == 3
