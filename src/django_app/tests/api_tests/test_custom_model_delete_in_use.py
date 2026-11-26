"""Deleting a custom model that configs still use is refused with the in-use error, which
names those configs; it used to delete them with it."""

import pytest
from ai_models.models import EmbeddingConfig, EmbeddingModel, LLMConfig, LLMModel, Provider

from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db


@pytest.fixture
def client(org_client_as, admin_acme, acme):
    return org_client_as(admin_acme, acme)


@pytest.fixture
def provider(db):
    return Provider.objects.get_or_create(name="openai")[0]


KINDS = [
    ("/api/llm-models/", LLMModel, "llm_provider", LLMConfig),
    ("/api/embedding-models/", EmbeddingModel, "embedding_provider", EmbeddingConfig),
]


@pytest.mark.parametrize(("url", "model_class", "provider_field", "config_class"), KINDS)
def test_custom_model_in_use_delete_refused(
    client, acme, provider, url, model_class, provider_field, config_class
):
    custom = model_class.objects.create(
        name="mine", org=acme, is_custom=True, **{provider_field: provider}
    )
    for name in ("Beta config", "Alpha config"):
        config_class.objects.create(custom_name=name, model=custom, org=acme)

    response = client.delete(f"{url}{custom.id}/")

    assert response.status_code == 403
    assert response.data["code"] == "in_use_restricted"
    assert "Alpha config, Beta config" in response.data["message"]
    assert model_class.objects.filter(id=custom.id).exists()
    assert config_class.objects.filter(model=custom).count() == 2


@pytest.mark.parametrize(("url", "model_class", "provider_field", "config_class"), KINDS)
def test_configs_of_another_organization_are_counted_never_named(
    client, acme, beta, provider, url, model_class, provider_field, config_class
):
    # Stored before configs were scoped: another organization's configs use acme's model.
    custom = model_class.objects.create(
        name="mine", org=acme, is_custom=True, **{provider_field: provider}
    )
    config_class.objects.create(custom_name="Acme config", model=custom, org=acme)
    for name in ("Beta secret project", "Beta other project"):
        config_class.objects.create(custom_name=name, model=custom, org=beta)

    response = client.delete(f"{url}{custom.id}/")

    assert response.status_code == 403
    assert response.data["message"] == (
        "This model is used by these configs: Acme config and 2 configs of another "
        "organization. Choose another model for them before deleting it."
    )
    assert model_class.objects.filter(id=custom.id).exists()


@pytest.mark.parametrize(("url", "model_class", "provider_field", "config_class"), KINDS)
def test_unused_custom_model_is_deleted(
    client, acme, provider, url, model_class, provider_field, config_class
):
    custom = model_class.objects.create(
        name="mine", org=acme, is_custom=True, **{provider_field: provider}
    )

    assert client.delete(f"{url}{custom.id}/").status_code == 204
    assert not model_class.objects.filter(id=custom.id).exists()


@pytest.mark.parametrize(("url", "model_class", "provider_field", "config_class"), KINDS)
def test_another_orgs_custom_model_is_not_found(
    client, beta, provider, url, model_class, provider_field, config_class
):
    theirs = model_class.objects.create(
        name="theirs", org=beta, is_custom=True, **{provider_field: provider}
    )

    assert client.delete(f"{url}{theirs.id}/").status_code == 404
    assert model_class.objects.filter(id=theirs.id).exists()
