import pytest
from ai_models.domain.specs import ModelKind
from ai_models.repository import CatalogRepository
from ai_models.services.config_validation import ConfigValidationService
from tables.exceptions import ConfigValidationError
from tables.services.secrets import secret_service

from tests.ai_models_tests.factories import make_runtime_catalog
from tests.rbac_cross_org_fixtures import acme, beta  # noqa: F401

pytestmark = pytest.mark.django_db

LLM = ModelKind.LLM
BEDROCK_REGION = {"aws_region_name": "eu-west-1"}


@pytest.fixture
def service():
    return ConfigValidationService(CatalogRepository(make_runtime_catalog()))


@pytest.fixture
def acme_secret(acme):  # noqa: F811
    return secret_service.create(text="AKIA-acme", org=acme, name="aws-key")


@pytest.fixture
def other_org_secret(beta):  # noqa: F811
    return secret_service.create(text="AKIA-beta", org=beta, name="beta-aws-key")


def _errors(service, *, kind=LLM, provider="openai", model="gpt-4o", parameters=None, connection=None, org_id=0):
    with pytest.raises(ConfigValidationError) as error_info:
        service.validate(kind, provider, model, parameters or {}, connection or {}, org_id)
    return error_info.value.detail


def test_valid_settings_and_connection_pass(service):
    assert (
        service.validate(
            LLM,
            "openai",
            "gpt-4o",
            {"temperature": 0.3, "max_tokens": 16384, "reasoning_effort": "low", "seed": None},
            {"base_url": "https://example.com/v1"},
            0,
        )
        is None
    )


def test_out_of_range_is_rejected_on_write(service):
    detail = _errors(service, provider="anthropic", model="claude-sonnet", parameters={"temperature": 1.5})

    assert list(detail) == ["parameters"]
    assert list(detail["parameters"]) == ["temperature"]
    assert "maximum" in str(detail["parameters"]["temperature"][0])


@pytest.mark.parametrize(("max_tokens", "rejected"), [(499, True), (500, False), (16384, False), (16385, True)])
def test_model_limit_is_enforced_on_both_sides(service, max_tokens, rejected):
    parameters = {"max_tokens": max_tokens}
    if rejected:
        assert "max_tokens" in _errors(service, parameters=parameters)["parameters"]
    else:
        service.validate(LLM, "openai", "gpt-4o", parameters, {}, 0)


def test_unknown_key_is_rejected(service):
    detail = _errors(service, parameters={"frequency_penalty": 0.0, "temperature": 0.5})

    assert list(detail["parameters"]) == ["frequency_penalty"]


def test_every_bad_field_is_reported_at_once(service):
    detail = _errors(service, parameters={"temperature": 3, "stop": [1], "unknown": 1})

    assert set(detail["parameters"]) == {"temperature", "stop", "unknown"}


@pytest.mark.parametrize("value", [[], "temperature", None])
def test_parameters_must_be_an_object(service, value):
    with pytest.raises(ConfigValidationError) as error_info:
        service.validate(LLM, "openai", "gpt-4o", value, {}, 0)

    assert "parameters" in error_info.value.detail


def test_unknown_and_missing_connection_fields_are_rejected(service, acme, acme_secret):  # noqa: F811
    detail = _errors(
        service,
        provider="bedrock",
        model="anthropic.claude-v2",
        connection={"aws_access_key_id": "epicstaff_secret(aws-key)", "region": "x"},
        org_id=acme.id,
    )

    assert set(detail["connection"]) == {"aws_region_name", "region"}


def test_plaintext_in_a_secret_field_is_rejected(service):
    detail = _errors(
        service,
        provider="bedrock",
        model="anthropic.claude-v2",
        connection={"aws_access_key_id": "AKIAEXAMPLE", **BEDROCK_REGION},
    )

    assert list(detail["connection"]) == ["aws_access_key_id"]


def test_errors_list_each_message_by_dotted_path_without_secret_or_undeclared_values(service, acme):  # noqa: F811
    with pytest.raises(ConfigValidationError) as error_info:
        service.validate(
            LLM,
            "bedrock",
            "anthropic.claude-v2",
            {"max_tokens": 0},
            {"aws_access_key_id": "AKIAEXAMPLE", "aws_region_name": "", "region": "sk-pasted"},
            acme.id,
        )

    entries = {entry["field"]: entry for entry in error_info.value.errors}
    assert set(entries) == {
        "parameters.max_tokens",
        "connection.aws_access_key_id",
        "connection.aws_region_name",
        "connection.region",
    }
    assert entries["parameters.max_tokens"]["value"] == 0
    assert entries["connection.aws_region_name"]["value"] == ""
    # A secret field's value, and a field the provider does not declare, are never echoed.
    assert "value" not in entries["connection.aws_access_key_id"]
    assert "value" not in entries["connection.region"]
    # Nor quoted in a message: the validator's own one for a pattern does.
    assert "AKIAEXAMPLE" not in str(error_info.value.errors)
    assert "AKIAEXAMPLE" not in str(error_info.value.detail)
    assert all(entry["reason"] for entry in error_info.value.errors)


def test_a_part_that_is_no_object_is_listed_under_its_own_name(service):
    with pytest.raises(ConfigValidationError) as error_info:
        service.validate(LLM, "openai", "gpt-4o", "hot", ["sk-pasted"], 0)

    assert error_info.value.errors == [
        {"field": "parameters", "value": "hot", "reason": "Must be an object."},
        {"field": "connection", "reason": "Must be an object."},
    ]


def test_marker_to_own_org_secret_is_accepted(service, acme, acme_secret):  # noqa: F811
    service.validate(
        LLM,
        "bedrock",
        "anthropic.claude-v2",
        {},
        {"aws_access_key_id": "epicstaff_secret(aws-key)", **BEDROCK_REGION},
        acme.id,
    )


def test_marker_to_other_org_secret_is_rejected_like_an_unknown_name(service, acme, other_org_secret):  # noqa: F811
    def connection_error(name):
        detail = _errors(
            service,
            provider="bedrock",
            model="anthropic.claude-v2",
            connection={"aws_access_key_id": f"epicstaff_secret({name})", **BEDROCK_REGION},
            org_id=acme.id,
        )
        assert list(detail) == ["connection"]
        return [str(message) for message in detail["connection"]["aws_access_key_id"]]

    other_org = connection_error("beta-aws-key")
    unknown = connection_error("no-such-key")

    assert other_org == ["No secret named 'beta-aws-key'."]
    assert unknown == ["No secret named 'no-such-key'."]


@pytest.mark.parametrize(
    ("provider", "model", "connection", "field"),
    [
        # A resolved marker in a plain field would put the secret's value into a URL.
        ("openai", "gpt-4o", {"base_url": "https://example.com/epicstaff_secret(aws-key)"}, "base_url"),
        ("bedrock", "anthropic.claude-v2", {"aws_region_name": "epicstaff_secret(aws-key)"}, "aws_region_name"),
        ("openai", "gpt-4o", {"undeclared": "epicstaff_secret(aws-key)"}, "undeclared"),
    ],
    ids=["endpoint", "plain-required", "undeclared"],
)
def test_marker_outside_a_secret_field_is_rejected_even_for_an_own_secret(
    service, acme, acme_secret, provider, model, connection, field  # noqa: F811
):
    detail = _errors(service, provider=provider, model=model, connection=connection, org_id=acme.id)

    assert list(detail) == ["connection"]
    assert "Secret markers are only allowed in secret fields." in [
        str(message) for message in detail["connection"][field]
    ]


def test_binned_secret_is_unknown(service, acme, acme_secret):  # noqa: F811
    acme_secret.delete()

    detail = _errors(
        service,
        provider="bedrock",
        model="anthropic.claude-v2",
        connection={"aws_access_key_id": "epicstaff_secret(aws-key)", **BEDROCK_REGION},
        org_id=acme.id,
    )

    assert list(detail["connection"]) == ["aws_access_key_id"]


def test_defaults_hold_every_set_default(service):
    # seed and stop default to "not set"; reasoning_effort's default "medium" is not
    # one of gpt-4o's levels, so it is not set either.
    assert service.defaults(LLM, "openai", "gpt-4o") == {
        "max_tokens": 4096,
        "temperature": 0.7,
        "top_p": 1.0,
    }


@pytest.mark.parametrize(
    ("model", "max_tokens"),
    [("gpt-4o-mini", 2048), ("claude-sonnet", 4096), ("my-fine-tune", 4096)],
)
def test_default_above_the_model_limit_is_clamped_to_it(service, model, max_tokens):
    provider = "anthropic" if model.startswith("claude") else "openai"

    assert service.defaults(LLM, provider, model)["max_tokens"] == max_tokens


def test_defaults_pass_validation(service):
    for provider, model in [("openai", "gpt-4o"), ("openai", "gpt-4o-mini"), ("anthropic", "claude-sonnet")]:
        service.validate(LLM, provider, model, service.defaults(LLM, provider, model), {}, 0)


def test_review_reasons_flag_out_of_range_without_raising(service):
    reasons = service.review_reasons(LLM, "anthropic", "claude-sonnet", {"temperature": 1.5}, {})

    assert len(reasons) == 1 and reasons[0].startswith("temperature: ")


def test_review_reasons_name_unsupported_keys(service):
    reasons = service.review_reasons(
        LLM, "anthropic", "claude-sonnet", {"frequency_penalty": 0.0}, {}
    )

    assert len(reasons) == 1 and reasons[0].startswith("frequency_penalty: ")


def test_review_reasons_are_empty_for_a_matching_config(service):
    assert service.review_reasons(LLM, "openai", "gpt-4o", {"temperature": 0.3}, {}) == []


def test_review_reasons_skip_a_setting_stored_as_null_as_the_run_does(service):
    # claude-sonnet does not take frequency_penalty; a null one is "not set" and never sent.
    assert service.review_reasons(
        LLM, "anthropic", "claude-sonnet", {"temperature": 0.3, "frequency_penalty": None}, {}
    ) == []


def test_review_reasons_name_a_missing_required_connection_field(service):
    assert service.review_reasons(LLM, "bedrock", "anthropic.claude-v2", {}, {}) == [
        "aws_region_name: This field is required."
    ]


@pytest.mark.parametrize(
    ("connection", "expected"),
    [
        # A key the data migration copied onto a provider that does not declare it.
        ({"api_version": "2024-06-01"}, ["api_version: Not supported for this provider and model."]),
        # A marker stored before markers were checked: the run drops it.
        (
            {"base_url": "https://attacker.test/?k=epicstaff_secret(PROD_DB_PASSWORD)"},
            ["base_url: Secret markers are only allowed in secret fields."],
        ),
    ],
    ids=["undeclared-key", "marker-outside-a-secret-field"],
)
def test_review_reasons_name_a_connection_field_validate_would_refuse(service, connection, expected):
    assert service.review_reasons(LLM, "openai", "gpt-4o", {}, connection) == expected


def test_an_update_resending_an_undeclared_field_unchanged_is_not_refused(service):
    stored = {"base_url": "https://gateway.example", "api_version": "2024-06-01"}

    service.validate(
        LLM,
        "openai",
        "gpt-4o",
        {},
        {**stored, "base_url": "https://new-gateway.example"},
        0,
        stored_connection=stored,
    )


@pytest.mark.parametrize(
    ("stored_connection", "connection"),
    [
        (None, {"api_version": "2024-06-01"}),
        ({"api_version": "2024-06-01"}, {"api_version": "2025-01-01"}),
        ({}, {"api_version": "2024-06-01"}),
    ],
    ids=["create", "update-changes-it", "update-adds-it"],
)
def test_an_undeclared_field_a_write_sets_is_refused(service, stored_connection, connection):
    with pytest.raises(ConfigValidationError) as error_info:
        service.validate(LLM, "openai", "gpt-4o", {}, connection, 0, stored_connection=stored_connection)

    assert error_info.value.detail == {
        "connection": {"api_version": ["Not supported for this provider and model."]}
    }


@pytest.mark.parametrize(
    "stored_connection",
    [None, BEDROCK_REGION],
    ids=["create-or-provider-change", "update-removes-it"],
)
def test_a_missing_required_connection_field_is_refused(service, stored_connection):
    with pytest.raises(ConfigValidationError) as error_info:
        service.validate(
            LLM, "bedrock", "anthropic.claude-v2", {}, {}, 0, stored_connection=stored_connection
        )

    assert error_info.value.detail == {"connection": {"aws_region_name": ["This field is required."]}}


def test_an_update_may_keep_a_required_connection_field_missing_that_was_missing(service):
    assert (
        service.validate(
            LLM, "bedrock", "anthropic.claude-v2", {"max_tokens": 1000}, {}, 0, stored_connection={}
        )
        is None
    )


@pytest.mark.parametrize(
    ("provider", "model", "custom_model", "expected"),
    [
        ("openai", "gpt-3.5-turbo-0301", False, ["Deprecated model."]),
        ("anthropic", "claude-retired", False, ["Model left the catalog."]),
        ("mystery", "mystery-1", False, ["Model left the catalog."]),
        # A predefined model the catalog dropped, of a provider that takes custom models.
        ("openai", "my-fine-tune", False, ["Model left the catalog."]),
        # An organization's own model was never in the catalog.
        ("openai", "my-fine-tune", True, []),
        ("anthropic", "claude-custom", True, []),
        # A custom model the catalog does know is checked like any catalog model.
        ("openai", "gpt-3.5-turbo-0301", True, ["Deprecated model."]),
    ],
)
def test_review_reasons_flag_the_model(service, provider, model, custom_model, expected):
    assert service.review_reasons(LLM, provider, model, {}, {}, custom_model=custom_model) == expected


def test_allowed_parameters_fits_values_to_the_model(service):
    allowed = service.allowed_parameters(
        LLM, "anthropic", "claude-sonnet", {"temperature": 1.5, "top_p": None, "frequency_penalty": 0.0}
    )

    # Anthropic allows temperature up to 1: 1.5 becomes the nearest limit.
    assert allowed == {"temperature": 1}


@pytest.mark.parametrize(
    ("parameters", "expected"),
    [
        # Above the model's own limit (max output 16384) and below the registry minimum (500).
        ({"max_tokens": 100000}, {"max_tokens": 16384}),
        ({"max_tokens": 10}, {"max_tokens": 500}),
        ({"temperature": -1}, {"temperature": 0}),
        # In range and offered: sent as stored.
        ({"temperature": 0.4, "reasoning_effort": "high"}, {"temperature": 0.4, "reasoning_effort": "high"}),
        # A choice the model no longer offers is left out, like "not set".
        ({"reasoning_effort": "medium"}, {}),
    ],
)
def test_allowed_parameters_fit_out_of_range_values_to_the_model(service, parameters, expected):
    assert service.allowed_parameters(LLM, "openai", "gpt-4o", parameters) == expected


@pytest.mark.parametrize(
    ("parameters", "expected"),
    [
        ({}, []),
        ({"temperature": 0.4, "max_tokens": 16384, "reasoning_effort": "high"}, []),
        ({"max_tokens": 16385}, ["max_tokens: 16385 is greater than the maximum of 16384"]),
        ({"max_tokens": 499}, ["max_tokens: 499 is less than the minimum of 500"]),
        ({"reasoning_effort": "medium"}, ["reasoning_effort: 'medium' is not one of ['low', 'high', None]"]),
        ({"frequency_penalty": 0.0}, ["frequency_penalty: Not supported for this provider and model."]),
    ],
    ids=["nothing-set", "all-fit", "above-the-model-limit", "below-the-minimum", "choice-not-offered", "not-taken"],
)
def test_parameter_problems_name_each_setting_the_model_does_not_accept(service, parameters, expected):
    assert service.parameter_problems(LLM, "openai", "gpt-4o", parameters) == expected


def test_drop_unsupported_keeps_out_of_range_values(service):
    kept = service.drop_unsupported(
        LLM, "anthropic", "claude-sonnet", {"temperature": 1.5, "top_p": None, "presence_penalty": 0.0}
    )

    assert kept == {"temperature": 1.5, "top_p": None}


def test_default_service_reads_the_committed_catalog():
    defaults = ConfigValidationService().defaults(LLM, "openai", "gpt-4o")

    assert defaults["temperature"] == 0.7
    assert defaults["max_tokens"] == 4096


@pytest.mark.parametrize("provider", ["bedrock", "sagemaker"])
def test_committed_catalog_takes_an_aws_config_without_an_access_key_id(provider):
    # Migrated configs send their main secret as a bearer api_key; only SigV4 reads the key id.
    assert (
        ConfigValidationService().validate(LLM, provider, "some-custom-model", {}, BEDROCK_REGION, 0)
        is None
    )


@pytest.mark.parametrize("provider", ["bedrock", "sagemaker", "vertex_ai"])
def test_committed_catalog_takes_a_config_with_an_empty_connection(provider):
    # Migrated configs have no region, project or location: the service environment supplies them.
    assert ConfigValidationService().validate(LLM, provider, "some-custom-model", {}, {}, 0) is None
