"""A config's secret reaches a custom destination only if a USE holder approved that binding.

The approver (`secret_binding_approved_by`) is recorded on writes that needed secrets:USE
and on saves by a USE holder; the payload builder (ConverterService) checks that the
approver still holds USE, failing closed. A catalog destination is never checked.
"""

from importlib import import_module

import pytest
from agents.models import AgentDefinition
from django.apps import apps
from django.utils import timezone
from rbac.authorship import RecordedLastEdit, record_last_edit, restore_last_edits
from rbac.models import OrganizationUser
from rbac.models.enums import Permission, ResourceType
from tables.models import (
    EmbeddingConfig,
    EmbeddingModel,
    Graph,
    LLMConfig,
    LLMModel,
    OpenAIRealtimeConfig,
    Provider,
    Session,
)
from tables.models.graph_models import AgentNode, Edge, StartNode
from tables.models.knowledge_models import (
    BaseRagType,
    DocumentContent,
    DocumentMetadata,
    NaiveRag,
    SourceCollection,
)
from rest_framework.test import APIClient
from tables.services.knowledge_services.indexing_service import IndexingService
from tables.services.quickstart_service import QuickstartService
from tables.services.converter_service import ConverterService
from tables.services.secrets import secret_service
from tables.services.secrets.exceptions import SecretInjectionDeniedError
from tables.services.secrets.injection_guard import secret_injection_guard
from tables.services.session_manager_service import SessionManagerService
from tables.services.trigger_spec import TriggerSpec
from tests.api_tests.role_grant_clients import FULL_CRUD, client_with_grants
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

approver_migration = import_module("tables.migrations.0273_secret_binding_approved_by")

SECRET_VALUE = "sk-injection-must-never-be-echoed"
ATTACKER_URL = "https://attacker.example"


@pytest.fixture
def provider():
    provider, _ = Provider.objects.get_or_create(name="openai")
    return provider


@pytest.fixture
def secret(acme):
    return secret_service.create(text=SECRET_VALUE, org=acme, name="INJECTION_KEY")


@pytest.fixture
def custom_model(acme, provider):
    return LLMModel.objects.create(
        name="exfil-model", llm_provider=provider, base_url=ATTACKER_URL, org=acme, is_custom=True
    )


@pytest.fixture
def catalog_model(provider):
    return LLMModel.objects.create(name="gpt-4o-catalog", llm_provider=provider)


def _llm_config(org, model, *, secret=None, extra_headers=None, approver=None, name="Injected"):
    return LLMConfig.objects.create(
        custom_name=name,
        model=model,
        org=org,
        api_key_secret=secret,
        extra_headers=extra_headers or {},
        secret_binding_approved_by=approver,
    )


def _reloaded(config):
    """The row as a payload builder loads it: its model selected, nothing else cached."""
    return type(config).objects.select_related("model").get(pk=config.pk)


def _convert(config):
    return ConverterService().convert_llm_config_data(_reloaded(config))


def _client(acme, django_user_model, *, email, secrets_bitmask):
    return client_with_grants(
        org=acme,
        django_user_model=django_user_model,
        email=email,
        resource_permissions={
            ResourceType.SECRETS.value: secrets_bitmask,
            ResourceType.LLM_CONFIGS.value: FULL_CRUD,
        },
    )


class TestInjection:
    def test_an_approver_with_use_lets_the_secret_through(self, acme, admin_acme, custom_model, secret):
        config = _llm_config(acme, custom_model, secret=secret, approver=admin_acme)

        data = _convert(config)

        assert data.api_key_secret_id == secret.pk
        assert data.base_url == ATTACKER_URL

    def test_no_approver_is_denied_with_a_reason_naming_the_config(
        self, acme, admin_acme, custom_model, secret
    ):
        # Even a last edit by a USE holder does not count: only an approval does.
        config = _llm_config(acme, custom_model, secret=secret)
        record_last_edit(config, admin_acme)

        with pytest.raises(SecretInjectionDeniedError) as denial:
            _convert(config)

        message = str(denial.value.detail)
        assert 'LLM config "Injected"' in message
        assert "re-save" in message
        assert SECRET_VALUE not in message

    def test_an_approver_who_lost_use_is_denied(self, acme, admin_acme, role_member, custom_model, secret):
        config = _llm_config(acme, custom_model, secret=secret, approver=admin_acme)
        OrganizationUser.objects.filter(user=admin_acme, org=acme).update(role=role_member)

        with pytest.raises(SecretInjectionDeniedError):
            _convert(config)

    def test_use_held_in_another_org_does_not_count(self, beta, admin_acme, provider):
        # Org Admin of acme only; the config belongs to beta.
        beta_model = LLMModel.objects.create(
            name="beta-model", llm_provider=provider, base_url=ATTACKER_URL, org=beta, is_custom=True
        )
        beta_secret = secret_service.create(text="sk-beta", org=beta, name="BETA_KEY")
        config = _llm_config(beta, beta_model, secret=beta_secret, approver=admin_acme)

        with pytest.raises(SecretInjectionDeniedError):
            _convert(config)

    def test_a_header_marker_carries_a_secret_too(self, acme, custom_model):
        config = _llm_config(acme, custom_model, extra_headers={"X-K": "epicstaff_secret(INJECTION_KEY)"})

        with pytest.raises(SecretInjectionDeniedError):
            _convert(config)

    def test_a_config_carrying_no_secret_is_not_checked(self, acme, custom_model):
        assert _convert(_llm_config(acme, custom_model)).api_key_secret_id is None

    def test_a_catalog_model_is_not_checked_and_costs_no_query(
        self, acme, catalog_model, secret, django_assert_num_queries
    ):
        config = _reloaded(_llm_config(acme, catalog_model, secret=secret))

        with django_assert_num_queries(0):
            data = ConverterService().convert_llm_config_data(config)

        assert data.api_key_secret_id == secret.pk

    def test_an_own_base_url_on_a_catalog_model_is_a_custom_destination(self, acme, catalog_model, secret):
        config = _llm_config(acme, catalog_model, secret=secret)
        LLMConfig.objects.filter(pk=config.pk).update(base_url=ATTACKER_URL)

        with pytest.raises(SecretInjectionDeniedError):
            _convert(config)

    def test_an_embedding_config_with_a_custom_model_is_checked(self, acme, provider, secret):
        model = EmbeddingModel.objects.create(
            name="exfil-embedder", embedding_provider=provider, base_url=ATTACKER_URL, org=acme, is_custom=True
        )
        config = EmbeddingConfig.objects.create(
            custom_name="Embedder", model=model, org=acme, api_key_secret=secret
        )

        with pytest.raises(SecretInjectionDeniedError):
            ConverterService().convert_embedding_config_to_pydantic(_reloaded(config))

    @pytest.mark.parametrize(
        "base_url,approver_fixture,denied",
        [
            (ATTACKER_URL, None, True),
            (ATTACKER_URL, "member_only", True),
            (ATTACKER_URL, "admin_acme", False),
            (None, None, False),
        ],
    )
    def test_an_openai_realtime_config_is_checked_on_its_base_url(
        self, request, acme, secret, base_url, approver_fixture, denied
    ):
        config = OpenAIRealtimeConfig.objects.create(
            custom_name="Voice",
            org=acme,
            api_key_secret=secret,
            base_url=base_url,
            secret_binding_approved_by=request.getfixturevalue(approver_fixture) if approver_fixture else None,
        )

        if denied:
            with pytest.raises(SecretInjectionDeniedError):
                secret_injection_guard.assert_injection_permitted(config)
        else:
            secret_injection_guard.assert_injection_permitted(config)

    def test_a_config_shared_by_many_nodes_is_checked_once_per_build(
        self, acme, admin_acme, custom_model, secret, django_assert_max_num_queries
    ):
        config = _reloaded(_llm_config(acme, custom_model, secret=secret, approver=admin_acme))
        converter = ConverterService()

        with secret_injection_guard.batch():
            converter.convert_llm_config_data(config)
            with django_assert_max_num_queries(0):
                converter.convert_llm_config_data(config)


class TestApprovalIsRecordedOnWrites:
    def test_attaching_a_secret_with_use_records_the_approver(
        self, acme, django_user_model, custom_model, secret
    ):
        client = _client(acme, django_user_model, email="approver@example.com", secrets_bitmask=int(Permission.READ | Permission.USE))
        config = _llm_config(acme, custom_model)

        response = client.patch(
            f"/api/llm-configs/{config.pk}/", {"api_key_secret_id": secret.pk}, format="json"
        )

        assert response.status_code == 200, response.json()
        assert "secret_binding_approved_by" not in response.json()
        config.refresh_from_db()
        assert config.secret_binding_approved_by == client.handler._force_user
        assert _convert(config).api_key_secret_id == secret.pk

    def test_a_temperature_edit_by_a_member_without_use_keeps_delivery_working(
        self, acme, admin_acme, django_user_model, custom_model, secret
    ):
        config = _llm_config(acme, custom_model, secret=secret, approver=admin_acme)
        member = _client(acme, django_user_model, email="tuner@example.com", secrets_bitmask=int(Permission.READ))

        response = member.patch(f"/api/llm-configs/{config.pk}/", {"temperature": 0.9}, format="json")

        assert response.status_code == 200, response.json()
        config.refresh_from_db()
        assert config.temperature == 0.9
        assert config.secret_binding_approved_by == admin_acme
        assert _convert(config).api_key_secret_id == secret.pk

    def test_an_admin_re_saving_an_unapproved_config_approves_it(
        self, acme, django_user_model, custom_model, secret
    ):
        config = _llm_config(acme, custom_model, secret=secret)
        admin = _client(acme, django_user_model, email="resaver@example.com", secrets_bitmask=int(Permission.READ | Permission.USE))

        response = admin.patch(f"/api/llm-configs/{config.pk}/", {"temperature": 0.7}, format="json")

        assert response.status_code == 200, response.json()
        config.refresh_from_db()
        assert config.secret_binding_approved_by == admin.handler._force_user

    def test_a_client_cannot_write_the_approver(self, acme, admin_acme, django_user_model, custom_model, secret):
        config = _llm_config(acme, custom_model, secret=secret)
        member = _client(acme, django_user_model, email="forger@example.com", secrets_bitmask=int(Permission.READ))

        member.patch(
            f"/api/llm-configs/{config.pk}/", {"secret_binding_approved_by": admin_acme.pk}, format="json"
        )

        config.refresh_from_db()
        assert config.secret_binding_approved_by is None


class TestSystemApiKey:
    def test_a_save_by_the_system_api_key_keeps_the_approver(
        self, acme, admin_acme, issue_api_key, custom_model, secret
    ):
        # The system principal is a superadmin, so it holds USE, but it is no person.
        config = _llm_config(acme, custom_model, secret=secret, approver=admin_acme)
        raw_key, _ = issue_api_key(user=None, name="approver-system-key")
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = client.patch(f"/api/llm-configs/{config.pk}/", {"temperature": 0.3}, format="json")

        assert response.status_code == 200, response.json()
        config.refresh_from_db()
        assert config.secret_binding_approved_by == admin_acme
        assert _convert(config).api_key_secret_id == secret.pk


class TestQuickstart:
    @pytest.mark.parametrize("user_fixture,approved", [("admin_acme", True), ("member_only", False)])
    def test_quickstart_approves_its_bundle_only_for_a_use_holder(
        self, request, acme, provider, user_fixture, approved
    ):
        user = request.getfixturevalue(user_fixture)

        result = QuickstartService().quickstart(
            provider="openai", org_id=acme.id, user=user, api_key="sk-quickstart"
        )

        assert result["success"], result
        configs = [
            result["llm_config"],
            result["embedding_config"],
            OpenAIRealtimeConfig.objects.get(org=acme, custom_name=result["config_name"]),
        ]
        expected = user if approved else None
        for config in configs:
            config.refresh_from_db()
            assert config.secret_binding_approved_by == expected
        # No catalog model exists here, so quickstart made org custom models.
        if approved:
            assert _convert(result["llm_config"]).api_key_secret_id is not None
        else:
            with pytest.raises(SecretInjectionDeniedError):
                _convert(result["llm_config"])


class TestIndexing:
    @pytest.mark.parametrize("approver_fixture", ["admin_acme", None])
    def test_indexing_emits_a_custom_embedders_key_only_when_approved(
        self, request, acme, provider, secret, approver_fixture
    ):
        model = EmbeddingModel.objects.create(
            name="index-embedder", embedding_provider=provider, base_url=ATTACKER_URL, org=acme, is_custom=True
        )
        embedder = EmbeddingConfig.objects.create(
            custom_name="Indexer",
            model=model,
            org=acme,
            api_key_secret=secret,
            secret_binding_approved_by=request.getfixturevalue(approver_fixture) if approver_fixture else None,
        )
        collection = SourceCollection.objects.create(collection_name="Indexed", org=acme)
        DocumentMetadata.objects.create(
            source_collection=collection,
            document_content=DocumentContent.objects.create(content=b"text"),
            file_name="doc.pdf",
            file_type="pdf",
            file_size=4,
        )
        naive_rag = NaiveRag.objects.create(
            base_rag_type=BaseRagType.objects.create(
                source_collection=collection, rag_type=BaseRagType.RagType.NAIVE
            ),
            embedder=embedder,
            rag_status=NaiveRag.NaiveRagStatus.NEW,
        )

        if approver_fixture:
            prepared = IndexingService.validate_and_prepare_indexing(naive_rag.naive_rag_id, "naive")
            assert prepared["embedder_api_key_secret_id"] == secret.pk
        else:
            with pytest.raises(SecretInjectionDeniedError):
                IndexingService.validate_and_prepare_indexing(naive_rag.naive_rag_id, "naive")


class TestSessionSurfacing:
    def test_a_denied_config_ends_the_session_in_error_and_publishes_nothing(
        self, acme, custom_model, secret, monkeypatch
    ):
        config = _llm_config(acme, custom_model, secret=secret)
        agent_definition = AgentDefinition.objects.create(
            org=acme,
            name="injector",
            instruction_list=[{"name": "Instruction_1.md", "content": "nothing"}],
            llm_config=config,
        )
        graph = Graph.objects.create(name="injection-flow", org=acme)
        start = StartNode.objects.create(graph=graph, variables={"variables": {}})
        agent_node = AgentNode.objects.create(
            graph=graph, agent_definition=agent_definition, node_name="agent_node"
        )
        Edge.objects.create(graph=graph, start_node_id=start.pk, end_node_id=agent_node.pk)
        published = []
        service = SessionManagerService()
        monkeypatch.setattr(
            service.redis_service.redis_client,
            "publish",
            lambda channel, message: published.append(message) or 2,
        )

        with pytest.raises(SecretInjectionDeniedError):
            service.run_session(graph_id=graph.pk, variables={}, trigger=TriggerSpec.manual())

        session = Session.objects.filter(graph_id=graph.pk).latest("pk")
        assert session.status == Session.SessionStatus.ERROR
        assert 'LLM config "Injected"' in session.status_data["reason"]
        assert SECRET_VALUE not in session.status_data["reason"]
        assert not published


class TestBackfillMigration:
    @pytest.mark.parametrize(
        "last_editor,creator,expected",
        [
            ("admin_acme", None, "admin_acme"),
            (None, "admin_acme", "admin_acme"),
            ("null editor", "admin_acme", "admin_acme"),
            ("member_only", "admin_acme", None),
            (None, "member_only", None),
            ("superadmin", None, "superadmin"),
        ],
    )
    def test_a_custom_secret_bearing_config_is_approved_only_by_a_current_use_holder(
        self, request, acme, custom_model, secret, last_editor, creator, expected
    ):
        config = _llm_config(acme, custom_model, secret=secret)
        if creator:
            LLMConfig.objects.filter(pk=config.pk).update(created_by=request.getfixturevalue(creator))
        if last_editor == "null editor":
            restore_last_edits([RecordedLastEdit(config, None, timezone.now())])
        elif last_editor:
            record_last_edit(config, request.getfixturevalue(last_editor))

        approver_migration.backfill_secret_binding_approvers(apps)

        config.refresh_from_db()
        expected_user = request.getfixturevalue(expected) if expected else None
        assert config.secret_binding_approved_by == expected_user

    def test_a_catalog_config_is_left_alone(self, acme, admin_acme, catalog_model, secret):
        config = _llm_config(acme, catalog_model, secret=secret)
        record_last_edit(config, admin_acme)

        approver_migration.backfill_secret_binding_approvers(apps)

        config.refresh_from_db()
        assert config.secret_binding_approved_by is None
