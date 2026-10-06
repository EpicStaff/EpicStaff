import pytest
from plugins.models import Plugin
from plugins.samples.zip_builder import build_sample_zip
from plugins.services import install_service, lifecycle_service
from plugins.services.install_service import PluginInstallService
from rbac.models import OrganizationUser
from tables.clients import KnowledgeClient
from tables.models import EmbeddingModel, LLMModel, Provider
from tables.services.session_manager_service import SessionManagerService
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.plugins_tests.helpers import SECRETS, upload
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend


@pytest.fixture
def openai_catalog(db):
    """The shared catalog models the sample's configs point at, as a real stack seeds them."""
    provider = Provider.objects.create(name="openai")
    yield {
        "provider": provider,
        "llm_model": LLMModel.objects.create(name="gpt-4o-mini", llm_provider=provider),
        "embedding_model": EmbeddingModel.objects.create(
            name="text-embedding-3-small", embedding_provider=provider
        ),
    }


@pytest.fixture
def storage_backend(monkeypatch):
    """The object store plugin installs write to, kept in memory."""
    backend = InMemoryStorageBackend()
    monkeypatch.setattr(install_service, "get_storage_backend", lambda **_: backend)
    monkeypatch.setattr(lifecycle_service, "get_storage_backend", lambda **_: backend)
    yield backend


@pytest.fixture
def org_client(client_as):
    """Factory -> an APIClient for `user`, with `org` as the active organization."""

    def _make(user, org):
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
        return client

    yield _make


@pytest.fixture
def admin_client(org_client, admin_acme, acme):
    yield org_client(admin_acme, acme)


@pytest.fixture
def member_of(django_user_model):
    """Factory -> a new user holding `role` in `org`."""

    def _make(org, role, email):
        user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
        OrganizationUser.objects.create(user=user, org=org, role=role)
        return user

    yield _make


@pytest.fixture
def sample_zip():
    yield build_sample_zip()



@pytest.fixture
def installed_plugin(admin_acme, acme, openai_catalog, storage_backend, sample_zip):
    """The sample plugin installed in Acme by its Org Admin; indexing is not started."""
    yield PluginInstallService().install(
        upload(sample_zip), secrets=SECRETS, user=admin_acme, org_id=acme.pk
    )


@pytest.fixture
def ready_plugin(installed_plugin):
    """The installed sample with its knowledge indexed."""
    Plugin.objects.filter(pk=installed_plugin.pk).update(state=Plugin.State.READY)
    installed_plugin.refresh_from_db()
    yield installed_plugin


@pytest.fixture
def index_calls(monkeypatch):
    """Every KnowledgeClient.index call, instead of reaching the knowledge service."""
    calls = []
    monkeypatch.setattr(KnowledgeClient, "index", lambda self, **kwargs: calls.append(kwargs))
    yield calls


@pytest.fixture
def stopped_sessions(monkeypatch):
    """Session ids a stop was published for, instead of reaching Redis."""
    stopped = []

    def _publish(session_id):
        stopped.append(session_id)
        return 2

    monkeypatch.setattr(SessionManagerService().redis_service, "publish_stop_session", _publish)
    yield stopped


@pytest.fixture
def published_sessions(monkeypatch):
    """Session ids whose data was published to crew, instead of reaching Redis."""
    published = []

    def _publish(*, session_data, org_id):
        published.append(session_data.id)
        return 2

    monkeypatch.setattr(SessionManagerService().redis_service, "publish_session_data", _publish)
    yield published
