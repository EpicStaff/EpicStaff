"""Stored LLM settings the catalog no longer lets their model take are removed, nothing else.

ai_models 0007 removes `temperature` / `top_p` / `top_k` a model's `parameter_names` no
longer lists, and `reasoning_effort` "none" a model's options no longer offer, so no config
is left needing review. The cases pin the committed catalog: Claude 4.7+ takes no sampling
settings, claude-opus-5-5 always thinks, claude-sonnet-5-5 can turn thinking off, Claude
4.6 and Gemini 3.6 still take sampling settings.
"""

import importlib

import pytest
from ai_models.models import LLMConfig
from ai_models.services.config_parameters import llm_config_parameters
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from loguru import logger

BEFORE = [("ai_models", "0006_own_org_custom_models")]
CLEANED = [("ai_models", "0007_remove_settings_models_no_longer_accept")]
CLEANUP_MIGRATION = importlib.import_module(
    "ai_models.migrations.0007_remove_settings_models_no_longer_accept"
)

# Case -> (provider, model row name, organization's own custom row, stored, expected after).
CASES = {
    "sampling_on_claude_5": (
        "anthropic",
        "claude-sonnet-5-5",
        False,
        {"temperature": 0.7, "top_p": 1.0, "max_tokens": 1000, "reasoning_effort": "low"},
        {"max_tokens": 1000, "reasoning_effort": "low"},
    ),
    "no_thinking_where_offered": (
        "anthropic",
        "claude-sonnet-5-5",
        False,
        {"reasoning_effort": "none"},
        {"reasoning_effort": "none"},
    ),
    "no_thinking_on_always_thinking": (
        "anthropic",
        "claude-opus-5-5",
        False,
        {"reasoning_effort": "none", "temperature": 1, "stop": ["END"]},
        {"stop": ["END"]},
    ),
    "high_effort_on_always_thinking": (
        "anthropic",
        "claude-opus-5-5",
        False,
        {"reasoning_effort": "high"},
        {"reasoning_effort": "high"},
    ),
    # A stored null is "not set"; it goes with the setting the model no longer takes.
    "sampling_on_bedrock_claude_5": (
        "bedrock",
        "us.anthropic.claude-sonnet-5-5",
        False,
        {"temperature": 0.2, "top_p": None},
        {},
    ),
    "sampling_on_claude_4_6": (
        "anthropic",
        "claude-sonnet-4-6",
        False,
        {"temperature": 0.7, "top_p": 0.9},
        {"temperature": 0.7, "top_p": 0.9},
    ),
    # Flagged by LiteLLM as refusing sampling, yet LiteLLM still sends it to Gemini 3+.
    "sampling_on_gemini_3": (
        "gemini",
        "gemini/gemini-3.6-flash",
        False,
        {"temperature": 0.4},
        {"temperature": 0.4},
    ),
    "unknown_custom_model": (
        "anthropic",
        "acme-claude-finetune",
        True,
        {"temperature": 0.5, "reasoning_effort": "none"},
        {"temperature": 0.5, "reasoning_effort": "none"},
    ),
}
CHANGED_CASES = (
    "sampling_on_claude_5",
    "no_thinking_on_always_thinking",
    "sampling_on_bedrock_claude_5",
)


def _migrate(targets):
    MigrationExecutor(connection).migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def _migrate_to_leaves():
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.fixture
def warnings():
    messages = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    yield messages
    logger.remove(sink_id)


def _seed(state_apps) -> dict[str, int]:
    get = state_apps.get_model
    acme = get("rbac", "Organization").objects.create(name="Cleanup Acme")
    config_ids = {}
    for case, (provider_name, model_name, custom, parameters, _) in CASES.items():
        provider = get("ai_models", "Provider").objects.get_or_create(name=provider_name)[0]
        model = get("ai_models", "LLMModel").objects.get_or_create(
            name=model_name,
            llm_provider=provider,
            org=acme if custom else None,
            defaults={"is_custom": custom, "predefined": not custom},
        )[0]
        config_ids[case] = (
            get("ai_models", "LLMConfig")
            .objects.create(org=acme, custom_name=case, model=model, parameters=parameters)
            .pk
        )
    return config_ids


def _stored_parameters(state_apps, config_ids: dict[str, int]) -> dict[str, dict]:
    configs = state_apps.get_model("ai_models", "LLMConfig").objects
    return {case: configs.get(pk=pk).parameters for case, pk in config_ids.items()}


@pytest.mark.django_db(transaction=True)
def test_removes_only_the_settings_the_catalog_model_no_longer_accepts(warnings):
    try:
        config_ids = _seed(_migrate(BEFORE))

        cleaned_apps = _migrate(CLEANED)

        assert _stored_parameters(cleaned_apps, config_ids) == {
            case: expected for case, (*_, expected) in CASES.items()
        }
        # One line, by field name and count alone: values are the user's.
        assert warnings == [warnings[0]]
        assert "Removed reasoning_effort, temperature, top_p from 3 LLM config(s)" in warnings[0]
        assert "0.7" not in warnings[0]
        # The acceptance criterion: no cleaned config is left needing review.
        for case in CHANGED_CASES:
            config = LLMConfig.objects.select_related("model__llm_provider").get(
                pk=config_ids[case]
            )
            llm_config_parameters(config)
    finally:
        _migrate_to_leaves()


@pytest.mark.django_db(transaction=True)
def test_running_again_changes_nothing(warnings):
    try:
        config_ids = _seed(_migrate(BEFORE))
        cleaned_apps = _migrate(CLEANED)
        cleaned = _stored_parameters(cleaned_apps, config_ids)
        warnings.clear()

        CLEANUP_MIGRATION.remove_settings_models_no_longer_accept(cleaned_apps, None)

        assert _stored_parameters(cleaned_apps, config_ids) == cleaned
        assert warnings == []
    finally:
        _migrate_to_leaves()


@pytest.mark.django_db(transaction=True)
def test_runs_on_an_empty_table(warnings):
    try:
        _migrate(BEFORE)

        cleaned_apps = _migrate(CLEANED)

        assert not cleaned_apps.get_model("ai_models", "LLMConfig").objects.exists()
        assert warnings == []
    finally:
        _migrate_to_leaves()


@pytest.mark.parametrize(
    "catalog_text",
    [
        None,
        "{not json",
        # A layout this migration does not know: models without parameter_names.
        (
            '{"providers": {"anthropic": {"aliases": [], "kinds": ["llm"]}}, '
            '"models": {"llm": {"anthropic": {"claude-opus-5-5": {}}}}}'
        ),
    ],
    ids=["missing", "not_json", "other_shape"],
)
@pytest.mark.django_db(transaction=True)
def test_unusable_catalog_removes_nothing(tmp_path_factory, monkeypatch, warnings, catalog_text):
    # Not tmp_path: tests/conftest.py makes it one shared folder other tests write a catalog to.
    catalog_path = tmp_path_factory.mktemp("catalog") / "catalog.json"
    if catalog_text is not None:
        catalog_path.write_text(catalog_text)
    monkeypatch.setattr(CLEANUP_MIGRATION, "CATALOG_PATH", catalog_path)
    try:
        config_ids = _seed(_migrate(BEFORE))

        cleaned_apps = _migrate(CLEANED)

        assert _stored_parameters(cleaned_apps, config_ids) == {
            case: stored for case, (_, _, _, stored, _) in CASES.items()
        }
        assert len(warnings) == 1 and str(catalog_path) in warnings[0]
    finally:
        _migrate_to_leaves()
