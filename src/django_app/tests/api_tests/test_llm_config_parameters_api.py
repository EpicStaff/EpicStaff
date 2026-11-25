"""The LLM config API on the model catalog: `parameters`, `connection`, and the model a
config names by provider and model name.

Business rules that live in the serializer are tested here, through the endpoint, as it
is their only interface. Models come from the committed catalog.
"""

import pytest
from ai_models.models import LLMConfig, LLMModel, Provider
from rbac.models.enums import Permission, ResourceType

from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

CONFIGS = "/api/llm-configs/"
MOVED = "Moved to parameters/connection."
REMOVED_FLAT_FIELDS = [
    "temperature",
    "top_p",
    "stop",
    "max_tokens",
    "presence_penalty",
    "frequency_penalty",
    "logit_bias",
    "seed",
    "logprobs",
    "top_logprobs",
    "reasoning_effort",
    "base_url",
    "api_version",
    "deployment_id",
    "deployment",
    "task_type",
]
# The registry defaults of gpt-4o (ai_models/data/parameter_registry.yaml).
GPT_4O_DEFAULTS = {
    "frequency_penalty": 0.0,
    "logprobs": False,
    "max_tokens": 4096,
    "presence_penalty": 0.0,
    "temperature": 0.7,
    "top_p": 1.0,
}
AZURE_BASE_URL = {"base_url": "https://acme.openai.azure.com"}


def _provider(name):
    return Provider.objects.get_or_create(name=name)[0]


def _builtin(provider_name, name, **fields):
    return LLMModel.objects.create(
        name=name, llm_provider=_provider(provider_name), predefined=True, **fields
    )


@pytest.fixture
def gpt_4o(db):
    return _builtin("openai", "gpt-4o")


@pytest.fixture
def claude(db):
    # Stored with the provider prefix; the catalog key is the bare name.
    return _builtin("anthropic", "anthropic/claude-haiku-4-5")


@pytest.fixture
def azure_gpt_4o(db):
    return _builtin("azure", "azure/gpt-4o")


@pytest.fixture
def client(org_client_as, admin_acme, acme):
    return org_client_as(admin_acme, acme)


def _create(client, **body):
    return client.post(CONFIGS, {"custom_name": "config", **body}, format="json")


# ---- create ----


def test_create_with_a_model_id_and_no_parameters_stores_the_model_defaults(client, gpt_4o):
    response = _create(client, model=gpt_4o.id)

    assert response.status_code == 201, response.data
    assert response.data["model"] == gpt_4o.id
    assert response.data["parameters"] == GPT_4O_DEFAULTS
    assert response.data["connection"] == {}
    assert (response.data["needs_review"], response.data["review_reasons"]) == (False, [])
    assert (response.data["provider"], response.data["model_name"]) == ("openai", "gpt-4o")
    assert LLMConfig.objects.get(id=response.data["id"]).parameters == GPT_4O_DEFAULTS


def test_create_stores_the_parameters_as_sent(client, gpt_4o):
    response = _create(client, model=gpt_4o.id, parameters={"temperature": 0.3})

    assert response.status_code == 201, response.data
    assert LLMConfig.objects.get(id=response.data["id"]).parameters == {"temperature": 0.3}


@pytest.mark.parametrize("field_name", REMOVED_FLAT_FIELDS)
def test_flat_field_gets_400_naming_it(client, gpt_4o, field_name):
    response = _create(client, model=gpt_4o.id, **{field_name: None})

    assert response.status_code == 400
    assert response.data["message"] == f"{field_name}: {MOVED}"
    assert not LLMConfig.objects.exists()


@pytest.mark.parametrize(
    ("parameters", "message_start"),
    [
        ({"temperature": 2.5}, "parameters: temperature: "),
        ({"verbosity": "low"}, "parameters: verbosity: Not supported"),
        ("hot", "parameters: Must be an object."),
    ],
)
def test_create_with_parameters_the_catalog_refuses_gets_400(
    client, gpt_4o, parameters, message_start
):
    response = _create(client, model=gpt_4o.id, parameters=parameters)

    assert response.status_code == 400
    assert response.data["message"].startswith(message_start), response.data
    assert not LLMConfig.objects.exists()


def test_create_without_a_required_connection_field_gets_400(client):
    azure_model = _builtin("azure", "azure/gpt-4o")

    response = _create(client, model=azure_model.id)

    assert response.status_code == 400
    assert response.data["message"] == "connection: base_url: This field is required."


def test_connection_field_is_stored(client):
    azure_model = _builtin("azure", "azure/gpt-4o")

    response = _create(
        client, model=azure_model.id, connection={"base_url": "https://acme.openai.azure.com"}
    )

    assert response.status_code == 201, response.data
    assert LLMConfig.objects.get(id=response.data["id"]).connection == {
        "base_url": "https://acme.openai.azure.com"
    }


@pytest.mark.parametrize(
    ("effort", "status_code"), [("minimal", 201), ("high", 201), ("xhigh", 400), ("max", 400)]
)
def test_reasoning_effort_takes_only_the_models_levels(client, effort, status_code):
    gpt_5_mini = _builtin("openai", "gpt-5-mini")

    response = _create(client, model=gpt_5_mini.id, parameters={"reasoning_effort": effort})

    assert response.status_code == status_code, response.data


# ---- the model named by provider and model name ----


def test_pair_resolves_the_visible_predefined_row_by_lookup_name(client, claude):
    response = _create(client, provider="anthropic", model_name="claude-haiku-4-5")

    assert response.status_code == 201, response.data
    assert response.data["model"] == claude.id
    assert LLMModel.objects.count() == 1


def test_pair_takes_a_provider_alias_and_either_name_form(client):
    gemini_row = _builtin("google_ai", "gemini/gemini-2.5-flash")

    response = _create(client, provider="gemini", model_name="gemini-2.5-flash")

    assert response.status_code == 201, response.data
    assert response.data["model"] == gemini_row.id
    assert not Provider.objects.filter(name="gemini").exists()


def test_unknown_model_creates_the_orgs_custom_row(client, acme, admin_acme):
    _provider("ollama")

    response = _create(client, provider="ollama", model_name="my-local-llm")

    assert response.status_code == 201, response.data
    custom = LLMModel.objects.get(id=response.data["model"])
    assert (custom.name, custom.llm_provider.name, custom.org_id) == ("my-local-llm", "ollama", acme.id)
    assert (custom.is_custom, custom.predefined, custom.created_by_id) == (True, False, admin_acme.id)
    # A custom model gets its provider's common settings.
    assert response.data["parameters"] == {
        "temperature": 0.7,
        "top_p": 1.0,
        "max_tokens": 4096,
        "frequency_penalty": 0.0,
    }
    assert (response.data["needs_review"], response.data["review_reasons"]) == (False, [])


def test_the_orgs_custom_row_is_reused(client):
    _provider("ollama")
    first = _create(client, provider="ollama", model_name="my-local-llm")

    second = client.post(
        CONFIGS,
        {"custom_name": "second", "provider": "ollama", "model_name": "my-local-llm"},
        format="json",
    )

    assert second.status_code == 201, second.data
    assert second.data["model"] == first.data["model"]
    assert LLMModel.objects.filter(name="my-local-llm").count() == 1


def test_another_orgs_custom_row_is_never_used(client, acme, beta):
    ollama = _provider("ollama")
    theirs = LLMModel.objects.create(name="my-local-llm", llm_provider=ollama, org=beta, is_custom=True)

    response = _create(client, provider="ollama", model_name="my-local-llm")

    assert response.status_code == 201, response.data
    assert response.data["model"] != theirs.id
    assert LLMModel.objects.get(id=response.data["model"]).org_id == acme.id


def test_a_hidden_predefined_row_is_not_resolved(client, acme):
    hidden = _builtin("openai", "gpt-retired", is_visible=False)

    response = _create(client, provider="openai", model_name="gpt-retired")

    assert response.status_code == 201, response.data
    assert response.data["model"] != hidden.id
    assert LLMModel.objects.get(id=response.data["model"]).org_id == acme.id


def test_unknown_model_of_a_provider_without_custom_models_gets_400(client, claude):
    response = _create(client, provider="anthropic", model_name="claude-imaginary")

    assert response.status_code == 400
    assert response.data["message"] == (
        "model_name: Unknown model 'claude-imaginary' for provider 'anthropic'."
    )
    assert LLMModel.objects.count() == 1 and not LLMConfig.objects.exists()


def test_unknown_provider_gets_400(client):
    response = _create(client, provider="nobody", model_name="x")

    assert response.status_code == 400
    assert response.data["message"] == "provider: Unknown provider 'nobody'."


@pytest.mark.parametrize(
    ("body", "message_start"),
    [
        ({"provider": "openai"}, "model_name: "),
        ({"model_name": "gpt-4o"}, "provider: "),
    ],
)
def test_half_a_pair_gets_400_naming_the_missing_half(client, gpt_4o, body, message_start):
    response = _create(client, **body)

    assert response.status_code == 400
    assert response.data["message"].startswith(message_start)


def test_model_id_and_a_pair_naming_another_model_get_400(client, gpt_4o):
    response = _create(client, model=gpt_4o.id, provider="openai", model_name="gpt-4o-mini")

    assert response.status_code == 400
    assert response.data["message"].startswith("model: ")
    assert not LLMConfig.objects.exists()


def test_model_id_of_another_orgs_custom_model_is_not_found(client, beta):
    theirs = LLMModel.objects.create(
        name="their-model", llm_provider=_provider("ollama"), org=beta, is_custom=True
    )

    response = _create(client, model=theirs.id)

    assert response.status_code == 400
    assert response.data["message"] == f'model: Invalid pk "{theirs.id}" - object does not exist.'


def test_creating_a_custom_row_on_update_needs_llm_configs_create(
    custom_role_member, org_client_as, acme
):
    _provider("ollama")
    config = LLMConfig.objects.create(custom_name="c", org=acme)
    editor = custom_role_member(
        acme, {ResourceType.LLM_CONFIGS: Permission.READ | Permission.UPDATE}, "llm-editor"
    )

    response = org_client_as(editor, acme).patch(
        f"{CONFIGS}{config.id}/", {"provider": "ollama", "model_name": "my-local-llm"}, format="json"
    )

    assert response.status_code == 403
    assert not LLMModel.objects.exists()


# ---- update ----


def test_update_parameters_out_of_range_gets_400(client, acme, claude):
    config = LLMConfig.objects.create(
        custom_name="c", model=claude, org=acme, parameters={"temperature": 0.5}
    )

    response = client.patch(
        f"{CONFIGS}{config.id}/", {"parameters": {"temperature": 1.5}}, format="json"
    )

    assert response.status_code == 400
    assert response.data["message"].startswith("parameters: temperature: ")
    config.refresh_from_db()
    assert config.parameters == {"temperature": 0.5}


@pytest.mark.parametrize("field_name", ["temperature", "base_url"])
def test_update_with_a_flat_field_gets_400(client, acme, gpt_4o, field_name):
    config = LLMConfig.objects.create(custom_name="c", model=gpt_4o, org=acme)

    response = client.patch(f"{CONFIGS}{config.id}/", {field_name: 0.2}, format="json")

    assert response.status_code == 400
    assert response.data["message"] == f"{field_name}: {MOVED}"


def test_rename_of_stale_config_saves(client, acme, claude):
    # Out of range for Anthropic: stored before the catalog limited it.
    config = LLMConfig.objects.create(
        custom_name="old", model=claude, org=acme, parameters={"temperature": 1.5}
    )

    response = client.patch(f"{CONFIGS}{config.id}/", {"custom_name": "new"}, format="json")

    assert response.status_code == 200, response.data
    config.refresh_from_db()
    assert (config.custom_name, config.parameters) == ("new", {"temperature": 1.5})
    assert response.data["needs_review"] is True


@pytest.mark.parametrize(
    "resent",
    [
        {"parameters": {"temperature": 1.5}},
        {"connection": {}},
        {"model": "claude"},
        {"provider": "anthropic", "model_name": "claude-haiku-4-5"},
    ],
    ids=["parameters", "connection", "model", "provider-and-name"],
)
def test_rename_resending_a_stale_configs_unchanged_settings_saves(client, acme, claude, resent):
    # An edit form sends every field back; only a change makes the catalog check them.
    config = LLMConfig.objects.create(
        custom_name="old", model=claude, org=acme, parameters={"temperature": 1.5}
    )
    body = {**resent, "model": claude.id} if "model" in resent else resent

    response = client.patch(f"{CONFIGS}{config.id}/", {"custom_name": "new", **body}, format="json")

    assert response.status_code == 200, response.data
    config.refresh_from_db()
    assert (config.custom_name, config.model_id, config.parameters) == ("new", claude.id, {"temperature": 1.5})


def test_one_changed_setting_on_a_stale_config_lists_every_invalid_field(client, acme, claude):
    config = LLMConfig.objects.create(
        custom_name="old", model=claude, org=acme, parameters={"temperature": 1.5, "retired": 1}
    )

    response = client.patch(
        f"{CONFIGS}{config.id}/",
        {"custom_name": "new", "parameters": {"temperature": 1.5, "retired": 2}},
        format="json",
    )

    assert response.status_code == 400
    assert [(entry["field"], entry["value"]) for entry in response.data["errors"]] == [
        ("parameters.temperature", 1.5),
        ("parameters.retired", 2),
    ]
    config.refresh_from_db()
    assert config.custom_name == "old"


def test_invalid_settings_get_400_listing_each_field_by_dotted_path(client, gpt_4o):
    response = _create(
        client,
        model=gpt_4o.id,
        parameters={"temperature": 2.5, "verbosity": "low"},
        connection={"base_url": 5},
    )

    assert response.status_code == 400
    assert (response.data["status_code"], response.data["code"]) == (400, "invalid")
    assert response.data["message"].startswith("parameters: temperature: ")
    errors = response.data["errors"]
    assert [(entry["field"], entry["value"]) for entry in errors] == [
        ("parameters.temperature", 2.5),
        ("parameters.verbosity", "low"),
        ("connection.base_url", 5),
    ]
    assert errors[1]["reason"] == "Not supported for this provider and model."
    assert all(entry["reason"] for entry in errors)
    assert not LLMConfig.objects.exists()


def test_update_keeping_a_missing_required_connection_field_missing_saves_and_needs_review(
    client, acme, azure_gpt_4o
):
    # The data migration leaves base_url out when the endpoint came from an environment variable.
    config = LLMConfig.objects.create(custom_name="c", model=azure_gpt_4o, org=acme)

    response = client.patch(
        f"{CONFIGS}{config.id}/", {"parameters": {"temperature": 0.3}}, format="json"
    )

    assert response.status_code == 200, response.data
    config.refresh_from_db()
    assert config.parameters == {"temperature": 0.3}
    assert (response.data["needs_review"], response.data["review_reasons"]) == (
        True,
        ["base_url: This field is required."],
    )


def test_an_edit_resending_a_migrated_undeclared_connection_field_saves_and_needs_review(
    client, acme, gpt_4o
):
    # The data migration copies a model row's api_version onto any provider's config.
    config = LLMConfig.objects.create(
        custom_name="c", model=gpt_4o, org=acme, connection={"api_version": "2024-06-01"}
    )

    response = client.patch(
        f"{CONFIGS}{config.id}/",
        {"connection": {"api_version": "2024-06-01", "base_url": "https://gateway.example/v1"}},
        format="json",
    )

    assert response.status_code == 200, response.data
    config.refresh_from_db()
    assert config.connection == {"api_version": "2024-06-01", "base_url": "https://gateway.example/v1"}
    assert (response.data["needs_review"], response.data["review_reasons"]) == (
        True,
        ["api_version: Not supported for this provider and model."],
    )


def test_an_oci_config_migrated_without_a_connection_can_be_renamed_and_edited(client, acme):
    oci_model = _builtin("oci", "oci/cohere.command-a-03-2025")
    config = LLMConfig.objects.create(custom_name="old", model=oci_model, org=acme)

    response = client.patch(
        f"{CONFIGS}{config.id}/",
        {"custom_name": "new", "parameters": {"temperature": 0.3}},
        format="json",
    )

    assert response.status_code == 200, response.data
    config.refresh_from_db()
    assert (config.custom_name, config.parameters, config.connection) == (
        "new",
        {"temperature": 0.3},
        {},
    )
    assert response.data["review_reasons"] == [
        f"{name}: This field is required."
        for name in ("oci_region", "oci_user", "oci_fingerprint", "oci_tenancy", "oci_compartment_id")
    ]


def test_changing_the_provider_without_its_required_connection_field_gets_400(
    client, acme, gpt_4o, azure_gpt_4o
):
    config = LLMConfig.objects.create(custom_name="c", model=gpt_4o, org=acme)

    response = client.patch(f"{CONFIGS}{config.id}/", {"model": azure_gpt_4o.id}, format="json")

    assert response.status_code == 400
    assert response.data["errors"] == [
        {"field": "connection.base_url", "value": None, "reason": "This field is required."}
    ]
    config.refresh_from_db()
    assert config.model_id == gpt_4o.id


@pytest.mark.parametrize(
    ("stored_connection", "sent_connection"),
    [(AZURE_BASE_URL, {}), ({}, {"base_url": ""})],
    ids=["removed", "set-to-an-invalid-value"],
)
def test_a_required_connection_field_the_update_touches_is_checked(
    client, acme, azure_gpt_4o, stored_connection, sent_connection
):
    config = LLMConfig.objects.create(
        custom_name="c", model=azure_gpt_4o, org=acme, connection=stored_connection
    )

    response = client.patch(
        f"{CONFIGS}{config.id}/", {"connection": sent_connection}, format="json"
    )

    assert response.status_code == 400
    assert [entry["field"] for entry in response.data["errors"]] == ["connection.base_url"]
    config.refresh_from_db()
    assert config.connection == stored_connection


def test_cross_org_config_404(client, beta, gpt_4o):
    theirs = LLMConfig.objects.create(custom_name="theirs", model=gpt_4o, org=beta)

    assert client.get(f"{CONFIGS}{theirs.id}/").status_code == 404
    response = client.patch(
        f"{CONFIGS}{theirs.id}/", {"parameters": {"temperature": 0.1}}, format="json"
    )
    assert response.status_code == 404
    theirs.refresh_from_db()
    assert theirs.parameters == {}


# ---- needs review ----


@pytest.mark.parametrize(
    ("model_name", "parameters", "custom", "expected_start"),
    [
        ("gpt-4o", {"temperature": 0.3}, False, []),
        ("gpt-4o", {"temperature": 9}, False, ["temperature: "]),
        ("gpt-4o", {"reasoning_effort": "low"}, False, ["reasoning_effort: "]),
        # A predefined row the catalog no longer lists.
        ("gpt-retired", {}, False, ["Model left the catalog."]),
        # An organization's own model was never in the catalog.
        ("my-fine-tune", {}, True, []),
    ],
)
def test_review_fields(client, acme, model_name, parameters, custom, expected_start):
    openai = _provider("openai")
    model = LLMModel.objects.create(
        name=model_name,
        llm_provider=openai,
        org=acme if custom else None,
        is_custom=custom,
        predefined=not custom,
    )
    config = LLMConfig.objects.create(custom_name="c", model=model, org=acme, parameters=parameters)

    data = client.get(f"{CONFIGS}{config.id}/").data

    assert data["needs_review"] is bool(expected_start)
    assert len(data["review_reasons"]) == len(expected_start)
    for reason, start in zip(data["review_reasons"], expected_start, strict=True):
        assert reason.startswith(start)


def test_list_computes_review_fields_without_a_query_per_config(
    client, acme, gpt_4o, claude, django_assert_max_num_queries
):
    LLMConfig.objects.create(custom_name="first", model=gpt_4o, org=acme)
    with django_assert_max_num_queries(100) as one_config:
        client.get(CONFIGS)
    for index in range(5):
        LLMConfig.objects.create(custom_name=f"more-{index}", model=claude, org=acme)

    with django_assert_max_num_queries(len(one_config.captured_queries)):
        response = client.get(CONFIGS)

    assert len(response.data["results"]) == 6
    assert all("needs_review" in row for row in response.data["results"])


# ---- model endpoints ----


@pytest.mark.parametrize("field_name", ["base_url", "api_version", "deployment_id"])
def test_llm_model_endpoint_field_gets_400(client, field_name):
    response = client.post(
        "/api/llm-models/",
        {"name": "m", "llm_provider": _provider("ollama").id, field_name: "x"},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["message"] == f"{field_name}: {MOVED}"


def test_llm_model_crud_has_no_endpoint_fields(client, acme):
    response = client.post(
        "/api/llm-models/", {"name": "m", "llm_provider": _provider("ollama").id}, format="json"
    )

    assert response.status_code == 201, response.data
    assert not {"base_url", "api_version", "deployment_id"} & response.data.keys()
    assert LLMModel.objects.get(id=response.data["id"]).org_id == acme.id


def test_llm_model_reasoning_levels_come_from_the_catalog(client, acme):
    gpt_5_mini = _builtin("openai", "gpt-5-mini")
    custom = LLMModel.objects.create(
        name="my-reasoner", llm_provider=_provider("openai"), org=acme, is_custom=True
    )

    rows = {
        row["id"]: row
        for row in client.get("/api/llm-models/", {"limit": 100}).data["results"]
    }

    assert rows[gpt_5_mini.id]["supports_reasoning"] is True
    assert rows[gpt_5_mini.id]["reasoning_efforts"] == ["minimal", "low", "medium", "high"]
    assert (rows[custom.id]["supports_reasoning"], rows[custom.id]["reasoning_efforts"]) == (
        False,
        [],
    )
