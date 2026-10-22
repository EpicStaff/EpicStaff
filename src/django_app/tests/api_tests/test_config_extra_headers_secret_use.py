"""An `epicstaff_secret(<name>)` marker in a config's extra_headers sends that
secret's plaintext with every run, so adding one needs secrets:USE, exactly like
changing `api_key_secret_id`. Markers already on the config, or removing them,
need no permission."""

import pytest
from rest_framework.test import APIClient

from rbac.models.enums import Permission, ResourceType
from tables.models import EmbeddingConfig, LLMConfig
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

MARKER_HEADERS = {"Authorization": "Bearer epicstaff_secret(GATEWAY_TOKEN)"}
LLM_CONFIGS_CRUD = Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE

CONFIGS = [
    ("/api/llm-configs/", LLMConfig),
    ("/api/embedding-configs/", EmbeddingConfig),
]


def _client(user, org):
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def no_use_client(custom_role_user, default_org):
    user = custom_role_user(
        default_org,
        "marker-nouse@example.com",
        {ResourceType.SECRETS: Permission.READ, ResourceType.LLM_CONFIGS: LLM_CONFIGS_CRUD},
    )
    return _client(user, default_org)


@pytest.fixture
def use_client(custom_role_user, default_org):
    user = custom_role_user(
        default_org,
        "marker-use@example.com",
        {
            ResourceType.SECRETS: Permission.READ | Permission.USE,
            ResourceType.LLM_CONFIGS: LLM_CONFIGS_CRUD,
        },
    )
    return _client(user, default_org)


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint, model", CONFIGS)
class TestHeaderMarkersNeedSecretsUse:
    def test_creating_with_a_marker_without_use_is_rejected(
        self, no_use_client, endpoint, model
    ):
        response = no_use_client.post(
            endpoint,
            {"custom_name": "marker-create", "extra_headers": MARKER_HEADERS},
            format="json",
        )

        assert response.status_code == 400, response.json()
        assert "extra_headers" in response.json()["message"]
        assert not model.objects.filter(custom_name="marker-create").exists()

    def test_adding_a_marker_without_use_is_rejected(
        self, no_use_client, endpoint, model, default_org
    ):
        config = model.objects.create(
            custom_name="marker-add", org=default_org, extra_headers={"X-Trace": "t"}
        )

        response = no_use_client.patch(
            f"{endpoint}{config.pk}/",
            {"extra_headers": {"X-Trace": "t", **MARKER_HEADERS}},
            format="json",
        )

        assert response.status_code == 400, response.json()
        assert "extra_headers" in response.json()["message"]
        config.refresh_from_db()
        assert config.extra_headers == {"X-Trace": "t"}

    def test_another_marker_name_in_the_same_header_is_rejected(
        self, no_use_client, endpoint, model, default_org
    ):
        config = model.objects.create(
            custom_name="marker-swap", org=default_org, extra_headers=MARKER_HEADERS
        )

        response = no_use_client.patch(
            f"{endpoint}{config.pk}/",
            {"extra_headers": {"Authorization": "Bearer epicstaff_secret(OTHER_SECRET)"}},
            format="json",
        )

        assert response.status_code == 400, response.json()
        config.refresh_from_db()
        assert config.extra_headers == MARKER_HEADERS

    def test_editing_other_fields_keeps_existing_markers_without_use(
        self, no_use_client, endpoint, model, default_org
    ):
        config = model.objects.create(
            custom_name="marker-keep", org=default_org, extra_headers=MARKER_HEADERS
        )

        renamed = no_use_client.patch(
            f"{endpoint}{config.pk}/", {"custom_name": "marker-renamed"}, format="json"
        )
        resent = no_use_client.patch(
            f"{endpoint}{config.pk}/",
            {"extra_headers": {**MARKER_HEADERS, "X-Trace": "plain"}},
            format="json",
        )

        assert renamed.status_code == 200, renamed.json()
        assert resent.status_code == 200, resent.json()
        config.refresh_from_db()
        assert config.custom_name == "marker-renamed"
        assert config.extra_headers == {**MARKER_HEADERS, "X-Trace": "plain"}

    def test_resending_a_marker_written_with_spaces_is_accepted(
        self, no_use_client, endpoint, model, default_org
    ):
        config = model.objects.create(
            custom_name="marker-spaces", org=default_org, extra_headers=MARKER_HEADERS
        )
        spaced = {"Authorization": "Bearer epicstaff_secret( GATEWAY_TOKEN )"}

        response = no_use_client.patch(
            f"{endpoint}{config.pk}/", {"extra_headers": spaced}, format="json"
        )

        assert response.status_code == 200, response.json()
        config.refresh_from_db()
        assert config.extra_headers == spaced

    def test_full_update_resending_existing_markers_is_accepted(
        self, no_use_client, endpoint, model, default_org
    ):
        config = model.objects.create(
            custom_name="marker-put", org=default_org, extra_headers=MARKER_HEADERS
        )

        response = no_use_client.put(
            f"{endpoint}{config.pk}/",
            {"custom_name": "marker-put-renamed", "extra_headers": MARKER_HEADERS},
            format="json",
        )

        assert response.status_code == 200, response.json()
        config.refresh_from_db()
        assert config.custom_name == "marker-put-renamed"
        assert config.extra_headers == MARKER_HEADERS

    def test_removing_markers_without_use_is_accepted(
        self, no_use_client, endpoint, model, default_org
    ):
        config = model.objects.create(
            custom_name="marker-remove", org=default_org, extra_headers=MARKER_HEADERS
        )

        response = no_use_client.patch(
            f"{endpoint}{config.pk}/", {"extra_headers": {}}, format="json"
        )

        assert response.status_code == 200, response.json()
        config.refresh_from_db()
        assert config.extra_headers == {}

    def test_plain_headers_without_use_are_accepted(self, no_use_client, endpoint, model):
        response = no_use_client.post(
            endpoint,
            {"custom_name": "plain-headers", "extra_headers": {"X-Trace": "t"}},
            format="json",
        )

        assert response.status_code == 201, response.json()

    def test_use_holder_can_add_markers(self, use_client, endpoint, model):
        response = use_client.post(
            endpoint,
            {"custom_name": "marker-use", "extra_headers": MARKER_HEADERS},
            format="json",
        )

        assert response.status_code == 201, response.json()
        assert model.objects.get(custom_name="marker-use").extra_headers == MARKER_HEADERS


@pytest.mark.django_db
def test_stored_headers_of_another_json_shape_do_not_break_an_update(
    no_use_client, default_org
):
    """LLM rows written before header validation may hold a non-object value."""
    config = LLMConfig.objects.create(
        custom_name="legacy-shape", org=default_org, extra_headers=["legacy"]
    )

    response = no_use_client.patch(
        f"/api/llm-configs/{config.pk}/", {"extra_headers": {"X-Trace": "t"}}, format="json"
    )

    assert response.status_code == 200, response.json()
