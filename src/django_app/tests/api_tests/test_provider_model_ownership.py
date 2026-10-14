"""The server, never the client, decides who owns a provider model row.

is_custom / predefined mark a row as a shared built-in; org and created_by say
whose it is. A client sending them must not be able to change any of them.
"""

import pytest
from rest_framework.test import APIClient

from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole
from tables.models import Provider
from tables.models.embedding_models import EmbeddingModel
from tables.models.llm_models import LLMModel, RealtimeModel, RealtimeTranscriptionModel

REGISTRIES = [
    ("llm-models", "llm_provider", LLMModel),
    ("embedding-models", "embedding_provider", EmbeddingModel),
    ("realtime-models", "provider", RealtimeModel),
    ("realtime-transcription-models", "provider", RealtimeTranscriptionModel),
]


@pytest.mark.django_db
@pytest.mark.parametrize("route,provider_field,model_cls", REGISTRIES)
def test_client_cannot_set_ownership_fields(django_user_model, route, provider_field, model_cls):
    org = Organization.objects.create(name="Org A")
    other_org = Organization.objects.create(name="Org B")
    admin = django_user_model.objects.create_user(email="admin_a@example.com", password="StrongPass123!")
    someone_else = django_user_model.objects.create_user(email="someone@example.com", password="StrongPass123!")
    role = Role.objects.get(name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True)
    OrganizationUser.objects.create(user=admin, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=admin)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    provider = Provider.objects.create(name="prov")

    response = client.post(
        f"/api/{route}/",
        {
            "name": "spoofed",
            provider_field: provider.id,
            "is_custom": False,
            "predefined": True,
            "org": other_org.id,
            "created_by": someone_else.id,
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    row = model_cls.objects.get(pk=response.data["id"])
    assert row.is_custom is True
    assert getattr(row, "predefined", False) is False
    assert (row.org_id, row.created_by_id) == (org.id, admin.id)
