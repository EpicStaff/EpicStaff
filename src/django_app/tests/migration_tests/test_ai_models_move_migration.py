"""The model-config models move from tables to ai_models without touching a row.

ai_models 0001, agents 0019 and tables 0291 change migration state only: the tables keep
their names, so every id and every foreign key stays as it is. ai_models 0002 relabels the
content types in place, so last-edit records and plugin ownership, which point at a content
type id, still find their configs. Migrating back reverses the relabel.
"""

from datetime import UTC, datetime

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from ai_models.models import EmbeddingConfig, LLMConfig
from plugins.models.ownership import PluginOwnedResource

BEFORE = [
    ("tables", "0290_systemoneconfig_openai_provider"),
    ("agents", "0018_merge_20261103_1638"),
    ("rbac", "0013_merge_20261106_1246"),
    ("plugins", "0011_package_navigation_icons"),
]
EDITED_AT = datetime(2026, 5, 6, 7, 8, 9, tzinfo=UTC)


def _migrate_before():
    executor = MigrationExecutor(connection)
    executor.migrate([*BEFORE, ("ai_models", None)])
    return MigrationExecutor(connection).loader.project_state(BEFORE).apps


def _migrate_to_leaves():
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def _seed(old_apps) -> dict:
    content_type_model = old_apps.get_model("contenttypes", "ContentType")
    organization = old_apps.get_model("rbac", "Organization").objects.create(name="Move Org")
    editor = old_apps.get_model("tables", "User").objects.create(email="editor@migration.test", password="!")
    provider = old_apps.get_model("tables", "Provider").objects.create(name="move-provider")
    secret = old_apps.get_model("tables", "Secret").objects.create(org=organization, name="MOVE_KEY", value="encrypted")
    llm_model = old_apps.get_model("tables", "LLMModel").objects.create(
        org=organization, name="move-llm", llm_provider=provider, is_custom=True
    )
    llm_config = old_apps.get_model("tables", "LLMConfig").objects.create(
        org=organization, custom_name="Move LLM", model=llm_model, api_key_secret=secret
    )
    embedding_model = old_apps.get_model("tables", "EmbeddingModel").objects.create(
        org=organization, name="move-embedding", embedding_provider=provider, is_custom=True
    )
    embedding_config = old_apps.get_model("tables", "EmbeddingConfig").objects.create(
        org=organization, custom_name="Move Embedding", model=embedding_model, api_key_secret=secret
    )
    agent = old_apps.get_model("agents", "AgentDefinition").objects.create(
        org=organization, name="Move Agent", llm_config=llm_config
    )
    default_models = old_apps.get_model("tables", "DefaultModels").objects.create(
        org=organization, agent_llm_config=llm_config, memory_embedding_config=embedding_config
    )
    llm_config_type, _ = content_type_model.objects.get_or_create(app_label="tables", model="llmconfig")
    embedding_config_type, _ = content_type_model.objects.get_or_create(
        app_label="tables", model="embeddingconfig"
    )
    old_apps.get_model("rbac", "ResourceLastEdit").objects.create(
        content_type=llm_config_type, object_id=llm_config.pk, edited_by=editor, edited_at=EDITED_AT
    )
    old_apps.get_model("plugins", "PluginOwnedResource").objects.create(
        org=organization,
        plugin_identifier="weather",
        content_type=embedding_config_type,
        object_id=embedding_config.pk,
    )
    return {
        "editor": editor.pk,
        "secret": secret.pk,
        "llm_model": llm_model.pk,
        "llm_config": llm_config.pk,
        "embedding_model": embedding_model.pk,
        "embedding_config": embedding_config.pk,
        "agent": agent.pk,
        "default_models": default_models.pk,
        "llm_config_type": llm_config_type.pk,
        "embedding_config_type": embedding_config_type.pk,
    }


def _assert_rows_unchanged(state_apps, app_label: str, seeded: dict) -> None:
    llm_config = state_apps.get_model(app_label, "LLMConfig").objects.get(pk=seeded["llm_config"])
    assert (llm_config.model_id, llm_config.api_key_secret_id) == (seeded["llm_model"], seeded["secret"])
    embedding_config = state_apps.get_model(app_label, "EmbeddingConfig").objects.get(
        pk=seeded["embedding_config"]
    )
    assert (embedding_config.model_id, embedding_config.api_key_secret_id) == (
        seeded["embedding_model"],
        seeded["secret"],
    )
    agent = state_apps.get_model("agents", "AgentDefinition").objects.get(pk=seeded["agent"])
    assert agent.llm_config_id == seeded["llm_config"]
    default_models = state_apps.get_model(app_label, "DefaultModels").objects.get(pk=seeded["default_models"])
    assert (default_models.agent_llm_config_id, default_models.memory_embedding_config_id) == (
        seeded["llm_config"],
        seeded["embedding_config"],
    )


def _content_types(state_apps) -> dict[str, list[tuple[int, str]]]:
    rows = state_apps.get_model("contenttypes", "ContentType").objects.filter(
        model__in=["llmconfig", "embeddingconfig"]
    )
    return {
        model_name: list(rows.filter(model=model_name).values_list("pk", "app_label"))
        for model_name in ("llmconfig", "embeddingconfig")
    }


@pytest.mark.django_db(transaction=True)
def test_model_configs_keep_their_rows_and_content_types_across_the_move():
    try:
        old_apps = _migrate_before()
        seeded = _seed(old_apps)
        # What post_migrate leaves behind when a migrate stops before the relabel: an empty
        # row under the new label, which must not displace the row the records point at.
        stray_type_pk = old_apps.get_model("contenttypes", "ContentType").objects.create(
            app_label="ai_models", model="llmconfig"
        ).pk

        _migrate_to_leaves()
        ContentType.objects.clear_cache()
        new_apps = MigrationExecutor(connection).loader.project_state().apps
        _assert_rows_unchanged(new_apps, "ai_models", seeded)
        assert _content_types(new_apps) == {
            "llmconfig": [(seeded["llm_config_type"], "ai_models")],
            "embeddingconfig": [(seeded["embedding_config_type"], "ai_models")],
        }
        assert not new_apps.get_model("contenttypes", "ContentType").objects.filter(pk=stray_type_pk).exists()

        assert ContentType.objects.get_for_model(LLMConfig).pk == seeded["llm_config_type"]
        last_edit = LLMConfig.objects.get(pk=seeded["llm_config"]).last_edits.get()
        assert (last_edit.edited_by_id, last_edit.edited_at) == (seeded["editor"], EDITED_AT)
        owned = PluginOwnedResource.objects.get(
            content_type=ContentType.objects.get_for_model(EmbeddingConfig),
            object_id=seeded["embedding_config"],
        )
        assert (owned.content_type_id, owned.plugin_identifier) == (
            seeded["embedding_config_type"],
            "weather",
        )

        reverted_apps = _migrate_before()
        _assert_rows_unchanged(reverted_apps, "tables", seeded)
        assert _content_types(reverted_apps) == {
            "llmconfig": [(seeded["llm_config_type"], "tables")],
            "embeddingconfig": [(seeded["embedding_config_type"], "tables")],
        }
        last_edit_model = reverted_apps.get_model("rbac", "ResourceLastEdit")
        assert last_edit_model.objects.get(object_id=seeded["llm_config"]).content_type_id == seeded["llm_config_type"]
        owned_model = reverted_apps.get_model("plugins", "PluginOwnedResource")
        assert (
            owned_model.objects.get(object_id=seeded["embedding_config"]).content_type_id
            == seeded["embedding_config_type"]
        )
    finally:
        ContentType.objects.clear_cache()
        _migrate_to_leaves()
