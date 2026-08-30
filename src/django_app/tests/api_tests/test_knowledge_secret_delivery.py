"""Indexing publishes resolved plaintext while the caller's object keeps neither
plaintext nor Secret id.

The knowledge service has no SECRET_KEY and no HTTP route to Django, so a Secret
id would be unresolvable there; Django must resolve at the publish boundary.
"""

import json
from unittest.mock import MagicMock

import pytest

from src.shared.models.knowledge import ProcessRagIndexingMessage
from tables.models.rbac_models import Organization
from tables.services.redis_service import RedisService
from tables.services.secrets import secret_service
from tables.services.secrets.exceptions import SecretResolutionError


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A KnowledgeDelivery")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B KnowledgeDelivery")


@pytest.fixture
def service(monkeypatch):
    """RedisService with a mocked client.

    `redis_client` is a property backed by `_redis_client`, so the backing
    attribute is what a test can set; monkeypatch restores it afterwards, which
    matters because RedisService is a singleton shared across tests.
    """
    instance = RedisService()
    client = MagicMock()
    monkeypatch.setattr(instance, "_redis_client", client)
    return instance, client


@pytest.mark.django_db
def test_publish_rag_indexing_sends_plaintext(org_a, service):
    instance, client = service
    secret = secret_service.create(text="sk-embedder-live", org=org_a, name="emb-key")

    instance.publish_rag_indexing(
        rag_id=1,
        rag_type="naive",
        collection_id=2,
        org_id=org_a.id,
        embedder_api_key_secret_id=secret.pk,
    )

    published = json.loads(client.publish.call_args.kwargs["message"])
    assert published["embedder_api_key"] == "sk-embedder-live"
    assert "embedder_api_key_secret_id" not in published


@pytest.mark.django_db
def test_the_unresolved_message_never_holds_plaintext(org_a):
    """resolve_payload deep-copies, so only the published copy carries plaintext."""
    secret = secret_service.create(text="sk-copy-check", org=org_a, name="copy-key")
    message = ProcessRagIndexingMessage(
        rag_id=1,
        rag_type="naive",
        collection_id=2,
        embedder_api_key_secret_id=secret.pk,
    )

    from tables.services.secrets.secret_resolver import secret_resolver

    resolved = secret_resolver.resolve_payload(payload=message, org_id=org_a.id)

    assert resolved.embedder_api_key == "sk-copy-check"
    assert message.embedder_api_key is None


@pytest.mark.django_db
def test_a_foreign_org_secret_is_rejected(org_a, org_b, service):
    instance, client = service
    foreign = secret_service.create(text="sk-org-b", org=org_b, name="b-emb-key")

    with pytest.raises(SecretResolutionError):
        instance.publish_rag_indexing(
            rag_id=1,
            rag_type="naive",
            collection_id=2,
            org_id=org_a.id,
            embedder_api_key_secret_id=foreign.pk,
        )

    client.publish.assert_not_called()


@pytest.mark.django_db
def test_no_secret_configured_publishes_no_credential(org_a, service):
    instance, client = service

    instance.publish_rag_indexing(
        rag_id=1, rag_type="naive", collection_id=2, org_id=org_a.id
    )

    published = json.loads(client.publish.call_args.kwargs["message"])
    assert published["embedder_api_key"] is None
