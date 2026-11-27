import json

from ai_models.domain.catalog import Catalog

from tests.ai_models_tests.factories import make_catalog, make_thinking_catalog


def test_catalog_round_trips_through_json():
    catalog = make_catalog()

    assert Catalog.from_json(catalog.to_json()) == catalog


def test_json_is_stable_sorted_and_indented():
    text = make_catalog().to_json()

    assert text == make_catalog().to_json()
    assert text == json.dumps(json.loads(text), sort_keys=True, indent=2)


def test_each_parameter_spec_is_stored_once():
    data = json.loads(make_catalog().to_json())

    llm_model = data["models"]["llm"]["openai"]["gpt-4o"]
    assert llm_model["parameter_names"] == ["reasoning_effort", "temperature"]
    assert data["parameters"]["temperature"]["default"] == 0.7
    assert make_catalog().to_json().count('"help_text"') == len(data["parameters"])


def test_default_thinking_round_trips_and_is_written_only_where_set():
    catalog = make_thinking_catalog()
    anthropic_models = json.loads(catalog.to_json())["models"]["llm"]["anthropic"]

    assert Catalog.from_json(catalog.to_json()) == catalog
    assert anthropic_models["claude-disabled"]["default_thinking"] == {
        "default_effort": "medium",
        "thinking_type_to_turn_off": "disabled",
        "provider_accepts_thinking": True,
    }
    assert "default_thinking" not in anthropic_models["claude-asks-to-think"]
