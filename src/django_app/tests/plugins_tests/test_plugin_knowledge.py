import pytest

from plugins.models import Plugin, PluginResource
from plugins.services import knowledge_service
from plugins.services.install_service import PluginInstallService
from plugins.services.knowledge_service import KnowledgeStatus, plugin_state_from_knowledge
from rbac.models import Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.clients.errors import ClientNotAvailableError
from tables.clients.knowledge import KnowledgeClient
from tables.models import EmbeddingConfig, LLMConfig, Secret, SourceCollection
from tables.models.knowledge_models import NaiveRag
from tables.services.secrets.encryption import secret_encryption
from tests.plugins_tests.helpers import SECRETS, plugin_url, registered_ids, upload

RagStatus = NaiveRag.NaiveRagStatus
READY, PREPARING, NEEDS_ATTENTION = (
    Plugin.State.READY,
    Plugin.State.PREPARING,
    Plugin.State.NEEDS_ATTENTION,
)


def _naive_rag(plugin) -> NaiveRag:
    [collection_id] = registered_ids(plugin, "source_collection")
    return NaiveRag.objects.get(base_rag_type__source_collection_id=collection_id)


def _set_rag_status(plugin, status: str) -> None:
    NaiveRag.objects.filter(pk=_naive_rag(plugin).pk).update(rag_status=status)


# --- the status mapping ------------------------------------------------------------


@pytest.mark.parametrize(
    "statuses, expected_state, expected_reason",
    [
        ([RagStatus.COMPLETED], READY, ""),
        ([RagStatus.COMPLETED, RagStatus.COMPLETED], READY, ""),
        ([], READY, ""),
        ([RagStatus.NEW], PREPARING, ""),
        ([RagStatus.PROCESSING], PREPARING, ""),
        ([RagStatus.COMPLETED, RagStatus.PROCESSING], PREPARING, ""),
        ([RagStatus.FAILED], NEEDS_ATTENTION, "Knowledge 'K0' failed to index."),
        ([RagStatus.CANCELLED], NEEDS_ATTENTION, "Knowledge 'K0' failed to index."),
        ([RagStatus.PARTIAL], NEEDS_ATTENTION, "Knowledge 'K0' failed to index."),
        ([RagStatus.COMPLETED, RagStatus.FAILED], NEEDS_ATTENTION, "Knowledge 'K1' failed to index."),
        ([RagStatus.PROCESSING, RagStatus.FAILED], NEEDS_ATTENTION, "Knowledge 'K1' failed to index."),
        ([None], NEEDS_ATTENTION, "Knowledge 'K0' was deleted."),
        ([RagStatus.COMPLETED, None], NEEDS_ATTENTION, "Knowledge 'K1' was deleted."),
        (
            [RagStatus.OUTDATED],
            NEEDS_ATTENTION,
            "Knowledge 'K0' is out of date and must be indexed again.",
        ),
    ],
)
def test_plugin_state_from_knowledge(statuses, expected_state, expected_reason):
    entries = [KnowledgeStatus(f"K{index}", status) for index, status in enumerate(statuses)]

    assert plugin_state_from_knowledge(entries) == (expected_state, expected_reason)


# --- starting indexing -------------------------------------------------------------


@pytest.mark.django_db
def test_install_starts_indexing_with_the_collection_documents_and_slot_key(
    admin_acme, acme, openai_catalog, storage_backend, sample_zip, index_calls,
    django_capture_on_commit_callbacks,
):
    with django_capture_on_commit_callbacks(execute=True):
        plugin = PluginInstallService().install(
            upload(sample_zip), secrets=SECRETS, user=admin_acme, org_id=acme.pk
        )

    naive_rag = _naive_rag(plugin)
    assert index_calls == [
        {
            "strategy": "naive",
            "rag_id": naive_rag.pk,
            "document_ids": frozenset(naive_rag.naive_rag_configs.values_list("pk", flat=True)),
            "embedding_api_key": SECRETS["OPENAI_API_KEY"],
            "llm_api_key": None,
        }
    ]
    assert len(index_calls[0]["document_ids"]) == 2
    plugin.refresh_from_db()
    assert plugin.state == PREPARING


@pytest.mark.django_db
def test_an_unreadable_slot_secret_makes_the_plugin_need_attention(installed_plugin, index_calls):
    Secret.objects.filter(pk__in=registered_ids(installed_plugin, "secret")).update(
        value="not-a-fernet-token"
    )

    knowledge_service.start_indexing(installed_plugin.pk)

    installed_plugin.refresh_from_db()
    assert installed_plugin.state == NEEDS_ATTENTION
    assert installed_plugin.status_reason.startswith(
        "Knowledge 'Acme Notes knowledge' could not start indexing:"
    )
    assert "not decryptable" in installed_plugin.status_reason
    assert index_calls == []


@pytest.mark.django_db
def test_an_unreachable_knowledge_service_makes_the_plugin_need_attention(
    installed_plugin, monkeypatch
):
    def _unreachable(self, **kwargs):
        raise ClientNotAvailableError("Knowledge service is unreachable.")

    monkeypatch.setattr(KnowledgeClient, "index", _unreachable)

    knowledge_service.start_indexing(installed_plugin.pk)

    installed_plugin.refresh_from_db()
    assert installed_plugin.state == NEEDS_ATTENTION
    assert installed_plugin.status_reason == (
        "Knowledge 'Acme Notes knowledge' could not start indexing: "
        "Knowledge service is unreachable."
    )


# --- status computed on read -------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "rag_status, expected_status, expected_reason",
    [
        (RagStatus.PROCESSING, "preparing", ""),
        (RagStatus.COMPLETED, "ready", ""),
        (RagStatus.FAILED, "needs_attention", "Knowledge 'Acme Notes knowledge' failed to index."),
    ],
)
def test_reading_a_preparing_plugin_settles_its_state(
    installed_plugin, admin_client, rag_status, expected_status, expected_reason
):
    _set_rag_status(installed_plugin, rag_status)

    detail = admin_client.get(plugin_url(installed_plugin)).json()
    [listed] = admin_client.get("/api/plugins/").json()

    assert detail["status"] == listed["status"] == expected_status
    assert detail["status_reason"] == expected_reason
    installed_plugin.refresh_from_db()
    assert installed_plugin.state == expected_status


@pytest.mark.django_db
@pytest.mark.parametrize("lost", ["collection", "registry row"])
def test_a_lost_collection_makes_the_plugin_need_attention(installed_plugin, admin_client, lost):
    collection_ids = registered_ids(installed_plugin, "source_collection")
    if lost == "collection":
        SourceCollection.objects.filter(pk__in=collection_ids).delete()
    else:
        PluginResource.objects.filter(
            plugin=installed_plugin, resource_type="source_collection"
        ).delete()

    body = admin_client.get(plugin_url(installed_plugin)).json()

    assert body["status"] == "needs_attention"
    assert body["status_reason"] == "Knowledge 'Acme Notes knowledge' was deleted."


@pytest.mark.django_db
def test_a_ready_plugin_is_not_reevaluated(ready_plugin, admin_client):
    _set_rag_status(ready_plugin, RagStatus.FAILED)

    assert admin_client.get(plugin_url(ready_plugin)).json()["status"] == "ready"


# --- retry -------------------------------------------------------------------------


@pytest.mark.django_db
def test_retry_reindexes_and_returns_preparing(installed_plugin, admin_client, index_calls):
    _set_rag_status(installed_plugin, RagStatus.FAILED)

    response = admin_client.post(plugin_url(installed_plugin, "retry"))

    assert response.status_code == 200, response.content
    assert response.json()["status"] == "preparing"
    assert response.json()["status_reason"] == ""
    assert [call["rag_id"] for call in index_calls] == [_naive_rag(installed_plugin).pk]
    # The knowledge service marks the RAG processing only later; until then the
    # next poll must not read the old failure and undo the retry.
    assert _naive_rag(installed_plugin).rag_status == RagStatus.NEW
    assert admin_client.get(plugin_url(installed_plugin)).json()["status"] == "preparing"


@pytest.mark.django_db
def test_retry_of_a_plugin_that_does_not_need_attention_is_409(
    ready_plugin, admin_client, index_calls
):
    response = admin_client.post(plugin_url(ready_plugin, "retry"))

    assert response.status_code == 409
    assert response.json()["code"] == "plugin_not_retryable"
    assert index_calls == []


@pytest.mark.django_db
def test_retry_of_a_suspended_plugin_is_409(installed_plugin, admin_client, index_calls):
    _set_rag_status(installed_plugin, RagStatus.FAILED)
    Plugin.objects.filter(pk=installed_plugin.pk).update(suspended=True)

    response = admin_client.post(plugin_url(installed_plugin, "retry"))

    assert response.status_code == 409
    assert response.json()["code"] == "plugin_suspended"
    assert index_calls == []


# --- re-entering secrets -----------------------------------------------------------


def _decrypted(secret_id: int) -> str:
    return secret_encryption.decrypt(encryptedtext=Secret.objects.get(pk=secret_id).value)


@pytest.mark.django_db
def test_secrets_replaces_the_slot_secret_and_keeps_its_bindings(
    installed_plugin, acme, admin_client, index_calls
):
    [old_secret_id] = registered_ids(installed_plugin, "secret")
    own_config = LLMConfig.objects.create(
        org=acme, custom_name="Mine", api_key_secret_id=old_secret_id
    )

    response = admin_client.post(
        plugin_url(installed_plugin, "secrets"), {"secrets": {"OPENAI_API_KEY": "sk-new"}}, format="json"
    )

    assert response.status_code == 200, response.content
    [new_secret_id] = registered_ids(installed_plugin, "secret")
    assert new_secret_id != old_secret_id
    assert not Secret.objects.filter(pk=old_secret_id).exists()
    new_secret = Secret.objects.get(pk=new_secret_id)
    assert new_secret.name == "CHAT_BOT__OPENAI_API_KEY"
    assert _decrypted(new_secret_id) == "sk-new"
    [llm_config_id] = registered_ids(installed_plugin, "llm_config")
    [embedding_config_id] = registered_ids(installed_plugin, "embedding_config")
    assert LLMConfig.objects.get(pk=llm_config_id).api_key_secret_id == new_secret_id
    assert EmbeddingConfig.objects.get(pk=embedding_config_id).api_key_secret_id == new_secret_id
    own_config.refresh_from_db()
    assert own_config.api_key_secret_id == new_secret_id
    assert response.json()["secret_slots"][0]["secret_id"] == new_secret_id
    assert index_calls == []


@pytest.mark.django_db
def test_secrets_recreates_a_deleted_slot_secret_and_binds_it_as_the_file_does(
    installed_plugin, admin_client
):
    Secret.objects.filter(pk__in=registered_ids(installed_plugin, "secret")).delete()

    response = admin_client.post(
        plugin_url(installed_plugin, "secrets"), {"secrets": {"OPENAI_API_KEY": "sk-again"}}, format="json"
    )

    assert response.status_code == 200, response.content
    assert response.json()["secret_slots"][0]["configured"] is True
    [secret_id] = registered_ids(installed_plugin, "secret")
    assert _decrypted(secret_id) == "sk-again"
    [llm_config_id] = registered_ids(installed_plugin, "llm_config")
    assert LLMConfig.objects.get(pk=llm_config_id).api_key_secret_id == secret_id


@pytest.mark.django_db
def test_secrets_with_retry_indexing_retries_a_plugin_that_needs_attention(
    installed_plugin, admin_client, index_calls
):
    _set_rag_status(installed_plugin, RagStatus.FAILED)

    response = admin_client.post(
        plugin_url(installed_plugin, "secrets"),
        {"secrets": {"OPENAI_API_KEY": "sk-fixed"}, "retry_indexing": True},
        format="json",
    )

    assert response.status_code == 200, response.content
    assert response.json()["status"] == "preparing"
    assert [call["embedding_api_key"] for call in index_calls] == ["sk-fixed"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "secrets, message",
    [
        ({}, "Enter a value for at least one secret slot."),
        ({"OPENAI_API_KEY": "   "}, "The value must not be blank."),
        ({"OTHER": "x"}, "The plugin has no such secret slot."),
        ({"OPENAI_API_KEY": "x" * 4097}, "The value is longer than 4096 characters."),
    ],
)
def test_secrets_rejects_values_that_do_not_fit_the_slots(
    installed_plugin, admin_client, secrets, message
):
    [secret_id] = registered_ids(installed_plugin, "secret")

    response = admin_client.post(
        plugin_url(installed_plugin, "secrets"), {"secrets": secrets}, format="json"
    )

    assert response.status_code == 400, response.content
    assert response.json()["code"] == "invalid_plugin_secrets"
    assert message in [error["message"] for error in response.json()["errors"]]
    assert registered_ids(installed_plugin, "secret") == [secret_id]


@pytest.mark.django_db
def test_secrets_needs_secret_create_as_well(installed_plugin, acme, member_of, org_client):
    role = Role.objects.create(name="Plugin keeper", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.PLUGINS.value, permissions=int(Permission.UPDATE)
    )
    client = org_client(member_of(acme, role, "keeper@acme.test"), acme)

    response = client.post(
        plugin_url(installed_plugin, "secrets"), {"secrets": {"OPENAI_API_KEY": "sk-x"}}, format="json"
    )

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
