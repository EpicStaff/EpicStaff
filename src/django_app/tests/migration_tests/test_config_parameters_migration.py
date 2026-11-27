"""Configs keep every row, secret link and default-role assignment when their columns fold into JSON.

The setting and endpoint columns move into `parameters` and `connection`.

ai_models 0003 adds the two JSON fields, 0004 folds the columns into them through the
committed model catalog, 0005 drops the columns. The fold drops only settings the model does
not take and keeps out-of-range values; an unreadable catalog drops nothing. Migrating back
restores what the fold kept.
"""

import importlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from loguru import logger

BEFORE = [("ai_models", "0002_move_content_types_from_tables")]
FOLDED = [("ai_models", "0004_fold_config_columns")]
FOLD_MIGRATION = importlib.import_module("ai_models.migrations.0004_fold_config_columns")

# Columns whose model default is not null; the release shape stores "not set" as null.
UNSET_SETTINGS = {
    "temperature": None,
    "top_p": None,
    "max_tokens": None,
    "presence_penalty": None,
    "frequency_penalty": None,
}
ACME_URL = "https://llm.acme.test/v1"
OVERRIDE_URL = "https://override.acme.test/v1"
EMBEDDING_URL = "https://embed.acme.test"


def _migrate(targets):
    MigrationExecutor(connection).migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def _migrate_to_leaves():
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def _leaf_apps():
    return MigrationExecutor(connection).loader.project_state().apps


@pytest.fixture
def warnings():
    messages = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    yield messages
    logger.remove(sink_id)


class _ReleaseShape:
    """Seeds the configs of the current release in the state before ai_models 0003."""

    def __init__(self, old_apps):
        self._get = old_apps.get_model
        self.acme = self._get("rbac", "Organization").objects.create(name="Fold Acme")
        self.beta = self._get("rbac", "Organization").objects.create(name="Fold Beta")
        secrets = self._get("tables", "Secret").objects
        self.acme_secret = secrets.create(org=self.acme, name="FOLD_KEY", value="encrypted")
        self.beta_secret = secrets.create(org=self.beta, name="FOLD_KEY", value="encrypted")

    def provider(self, name):
        return self._get("ai_models", "Provider").objects.get_or_create(name=name)[0]

    def llm_model(self, provider, name, org=None, **endpoints):
        return self._get("ai_models", "LLMModel").objects.create(
            name=name,
            llm_provider=self.provider(provider),
            org=org,
            is_custom=org is not None,
            predefined=org is None,
            **endpoints,
        )

    def llm_config(self, name, model, org=None, **columns):
        org = org or self.acme
        secret = self.acme_secret if org == self.acme else self.beta_secret
        return self._get("ai_models", "LLMConfig").objects.create(
            org=org,
            custom_name=name,
            model=model,
            api_key_secret=secret,
            **{**UNSET_SETTINGS, **columns},
        )

    def embedding_config(self, name, provider, model_name, task_type, org=None, **endpoints):
        model = self._get("ai_models", "EmbeddingModel").objects.create(
            name=model_name,
            embedding_provider=self.provider(provider),
            org=org,
            is_custom=org is not None,
            predefined=org is None,
            **endpoints,
        )
        return self._get("ai_models", "EmbeddingConfig").objects.create(
            org=self.acme,
            custom_name=name,
            model=model,
            task_type=task_type,
            api_key_secret=self.acme_secret,
        )


def _seed(old_apps) -> dict:
    shape = _ReleaseShape(old_apps)
    acme_model = shape.llm_model(
        "openai",
        "acme-finetune",
        org=shape.acme,
        base_url=ACME_URL,
        api_version="2024-10-21",
        deployment_id="acme-deploy",
    )
    unused_model = shape.llm_model(
        "openai", "acme-unused", org=shape.acme, base_url="https://unused.acme.test/v1"
    )
    configs = {
        "openai": shape.llm_config(
            "OpenAI",
            shape.llm_model("openai", "gpt-4o"),
            temperature=0.3,
            top_p=0.9,
            extra_headers={"X-Team": "epic"},
            timeout=45.0,
            input_cost_per_token=0.000001,
            output_cost_per_token=0.000002,
            context_window=64000,
        ),
        # A model that takes sampling settings: Claude 4.7 and later take none.
        "anthropic": shape.llm_config(
            "Anthropic",
            shape.llm_model("anthropic", "claude-sonnet-4-6"),
            temperature=1.5,
            top_p=1.0,
            max_tokens=4096,
            presence_penalty=0.0,
            frequency_penalty=0.0,
        ),
        # Catalog key "claude-opus-5-5"; reasoning_effort is in the model's list only.
        "prefixed_name": shape.llm_config(
            "Prefixed",
            shape.llm_model("anthropic", "anthropic/claude-opus-5-5"),
            reasoning_effort="high",
            presence_penalty=0.5,
        ),
        # A database alias of gemini, and a bare name whose catalog key is
        # "gemini/gemini-2.5-flash"; seed is in the model's list only.
        "aliased_provider": shape.llm_config(
            "Aliased",
            shape.llm_model("google_ai", "gemini-2.5-flash"),
            temperature=0.5,
            seed=7,
            logit_bias={"50256": -100},
        ),
        "custom_model": shape.llm_config(
            "Custom", acme_model, temperature=0.2, reasoning_effort="high"
        ),
        "custom_model_own_url": shape.llm_config("Custom own URL", acme_model, base_url=OVERRIDE_URL),
        "other_org_on_custom_model": shape.llm_config(
            "Other org", acme_model, org=shape.beta, temperature=0.2
        ),
        "no_model": shape.llm_config(
            "No model", None, temperature=0.4, seed=11, base_url="https://no-model.test"
        ),
        "unknown_provider": shape.llm_config(
            "Unknown provider",
            shape.llm_model("mystery_ai", "mystery-1"),
            temperature=0.1,
            stop=["END"],
            logit_bias={"1": 1},
        ),
        "embedding": shape.embedding_config(
            "Embedding",
            "google_ai",
            "acme-embed",
            "retrieval_query",
            org=shape.acme,
            base_url=EMBEDDING_URL,
            deployment="embed-deploy",
        ),
        "openai_embedding": shape.embedding_config(
            "OpenAI embedding", "openai", "text-embedding-3-small", "retrieval_document"
        ),
    }
    default_models = old_apps.get_model("ai_models", "DefaultModels").objects.create(
        org=shape.acme,
        agent_llm_config=configs["openai"],
        memory_llm_config=configs["anthropic"],
        memory_embedding_config=configs["embedding"],
    )
    return {
        "configs": {name: (type(config).__name__, config.pk) for name, config in configs.items()},
        "secrets": {name: config.api_key_secret_id for name, config in configs.items()},
        "acme_model": acme_model.pk,
        "unused_model": unused_model.pk,
        "embedding_model": configs["embedding"].model_id,
        "default_models": default_models.pk,
    }


def _config(state_apps, seeded: dict, name: str):
    model_name, pk = seeded["configs"][name]
    return state_apps.get_model("ai_models", model_name).objects.get(pk=pk)


def _assert_links_unchanged(state_apps, seeded: dict) -> None:
    for name in seeded["configs"]:
        assert _config(state_apps, seeded, name).api_key_secret_id == seeded["secrets"][name], name
    default_models = state_apps.get_model("ai_models", "DefaultModels").objects.get(
        pk=seeded["default_models"]
    )
    assert (
        default_models.agent_llm_config_id,
        default_models.memory_llm_config_id,
        default_models.memory_embedding_config_id,
    ) == (
        seeded["configs"]["openai"][1],
        seeded["configs"]["anthropic"][1],
        seeded["configs"]["embedding"][1],
    )
    openai = _config(state_apps, seeded, "openai")
    assert (
        openai.extra_headers,
        openai.timeout,
        openai.input_cost_per_token,
        openai.output_cost_per_token,
        openai.context_window,
    ) == ({"X-Team": "epic"}, 45.0, 0.000001, 0.000002, 64000)


EXPECTED_FOLD = {
    "openai": ({"temperature": 0.3, "top_p": 0.9}, {}),
    # Out of range for Anthropic, kept; the penalties Anthropic does not take are dropped.
    "anthropic": ({"temperature": 1.5, "top_p": 1.0, "max_tokens": 4096}, {}),
    "prefixed_name": ({"reasoning_effort": "high"}, {}),
    "aliased_provider": ({"temperature": 0.5, "seed": 7}, {}),
    # A custom model gets OpenAI's common list.
    "custom_model": (
        {"temperature": 0.2, "reasoning_effort": "high"},
        {"base_url": ACME_URL, "api_version": "2024-10-21", "deployment_id": "acme-deploy"},
    ),
    # Runs read the endpoint from the model row only, so the row's base_url wins.
    "custom_model_own_url": (
        {},
        {"base_url": ACME_URL, "api_version": "2024-10-21", "deployment_id": "acme-deploy"},
    ),
    # Another organization's model row never hands over its endpoint.
    "other_org_on_custom_model": ({"temperature": 0.2}, {}),
    "no_model": ({"temperature": 0.4, "seed": 11}, {"base_url": "https://no-model.test"}),
    "unknown_provider": (
        {"temperature": 0.1, "stop": ["END"], "logit_bias": {"1": 1}},
        {},
    ),
    "embedding": (
        {"task_type": "retrieval_query"},
        {"base_url": EMBEDDING_URL, "deployment_id": "embed-deploy"},
    ),
    "openai_embedding": ({}, {}),
}


@pytest.mark.django_db(transaction=True)
def test_configs_fold_into_parameters_and_connection_and_back(warnings):
    try:
        seeded = _seed(_migrate(BEFORE))

        _migrate_to_leaves()
        new_apps = _leaf_apps()
        _assert_links_unchanged(new_apps, seeded)
        folded = {
            name: (
                _config(new_apps, seeded, name).parameters,
                _config(new_apps, seeded, name).connection,
            )
            for name in seeded["configs"]
        }
        assert folded == EXPECTED_FOLD
        # The committed catalog was understood: nothing fell back to keeping every key. One
        # warning names the other org's config that did not take the row's endpoint, one the
        # custom model whose endpoint no config took; both by id and field name alone.
        assert len(warnings) == 2
        other_org = _config(new_apps, seeded, "other_org_on_custom_model")
        assert f"into LLMConfig id={other_org.pk}" in warnings[0]
        assert "base_url, api_version, deployment_id" in warnings[0]
        assert f"custom LLMModel id={seeded['unused_model']}:" in warnings[1]
        assert not any("acme.test" in warning for warning in warnings)

        old_apps = _migrate(BEFORE)
        _assert_links_unchanged(old_apps, seeded)
        openai = _config(old_apps, seeded, "openai")
        assert (openai.temperature, openai.top_p, openai.max_tokens) == (0.3, 0.9, None)
        anthropic = _config(old_apps, seeded, "anthropic")
        assert (anthropic.temperature, anthropic.top_p, anthropic.max_tokens) == (1.5, 1.0, 4096)
        unknown = _config(old_apps, seeded, "unknown_provider")
        assert (unknown.stop, unknown.logit_bias) == (["END"], {"1": 1})
        assert _config(old_apps, seeded, "custom_model").base_url == ACME_URL
        # Lossy: the config's own base_url, which no run read, did not survive the fold.
        assert _config(old_apps, seeded, "custom_model_own_url").base_url == ACME_URL
        assert _config(old_apps, seeded, "embedding").task_type == "retrieval_query"
        acme_model = old_apps.get_model("ai_models", "LLMModel").objects.get(pk=seeded["acme_model"])
        # The org's two configs agree on the row's endpoint, so it is restored.
        assert (acme_model.base_url, acme_model.api_version, acme_model.deployment_id) == (
            ACME_URL,
            "2024-10-21",
            "acme-deploy",
        )
        embedding_model = old_apps.get_model("ai_models", "EmbeddingModel").objects.get(
            pk=seeded["embedding_model"]
        )
        assert (embedding_model.base_url, embedding_model.deployment) == (
            EMBEDDING_URL,
            "embed-deploy",
        )
    finally:
        _migrate_to_leaves()


@pytest.mark.parametrize(
    "catalog_text",
    [
        None,
        "{not json",
        # A layout this migration does not know: providers without aliases.
        '{"providers": {"anthropic": {"kinds": ["llm"]}}, "models": {"llm": {}, "embedding": {}}}',
    ],
    ids=["missing", "not_json", "other_shape"],
)
@pytest.mark.django_db(transaction=True)
def test_unusable_catalog_keeps_every_setting(tmp_path_factory, monkeypatch, warnings, catalog_text):
    # Not tmp_path: tests/conftest.py makes it one shared folder other tests write a catalog to.
    catalog_path = tmp_path_factory.mktemp("catalog") / "catalog.json"
    if catalog_text is not None:
        catalog_path.write_text(catalog_text)
    monkeypatch.setattr(FOLD_MIGRATION, "CATALOG_PATH", catalog_path)
    try:
        shape = _ReleaseShape(_migrate(BEFORE))
        config = shape.llm_config(
            "Anthropic",
            shape.llm_model("anthropic", "claude-sonnet-5-5"),
            temperature=1.5,
            presence_penalty=0.0,
            seed=3,
        )
        embedding = shape.embedding_config(
            "OpenAI embedding", "openai", "text-embedding-3-small", "retrieval_document"
        )

        folded_apps = _migrate(FOLDED)

        assert folded_apps.get_model("ai_models", "LLMConfig").objects.get(
            pk=config.pk
        ).parameters == {"temperature": 1.5, "presence_penalty": 0.0, "seed": 3}
        assert folded_apps.get_model("ai_models", "EmbeddingConfig").objects.get(
            pk=embedding.pk
        ).parameters == {"task_type": "retrieval_document"}
        assert len(warnings) == 1 and str(catalog_path) in warnings[0]
    finally:
        _migrate_to_leaves()
