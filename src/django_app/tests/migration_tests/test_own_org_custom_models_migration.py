"""Configs on another organization's custom model move to a row of their own organization.

ai_models 0006 repoints them, so the RESTRICT config → model link from 0005 no longer blocks
deleting the organization that owns the row.
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("ai_models", "0005_drop_folded_config_columns")]
OWNED = [("ai_models", "0006_own_org_custom_models")]


def _migrate(targets):
    MigrationExecutor(connection).migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def _migrate_to_leaves():
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


class _LegacyShape:
    """Seeds configs in the state before ai_models 0006, cross-org links included."""

    def __init__(self, state_apps):
        self._get = state_apps.get_model
        organizations = self._get("rbac", "Organization").objects
        self.acme = organizations.create(name="Own Acme")
        self.beta = organizations.create(name="Own Beta")
        self.provider = self._get("ai_models", "Provider").objects.get_or_create(name="openai")[0]

    def llm_model(self, name, org, **fields):
        return self._get("ai_models", "LLMModel").objects.create(
            name=name, llm_provider=self.provider, org=org, is_custom=org is not None, **fields
        )

    def llm_config(self, name, model, org):
        return self._get("ai_models", "LLMConfig").objects.create(
            org=org, custom_name=name, model=model
        )

    def embedding_model(self, name, org):
        return self._get("ai_models", "EmbeddingModel").objects.create(
            name=name, embedding_provider=self.provider, org=org, is_custom=True
        )

    def embedding_config(self, name, model, org):
        return self._get("ai_models", "EmbeddingConfig").objects.create(
            org=org, custom_name=name, model=model
        )


@pytest.mark.django_db(transaction=True)
def test_configs_move_to_a_custom_model_row_of_their_own_org():
    try:
        shape = _LegacyShape(_migrate(BEFORE))
        acme, beta = shape.acme, shape.beta
        acme_finetune = shape.llm_model(
            "acme-finetune", acme, is_visible=False, description="Tuned by Acme"
        )
        acme_shared = shape.llm_model("shared-name", acme)
        beta_shared = shape.llm_model("shared-name", beta)
        builtin = shape.llm_model("own-org-builtin", None, predefined=True)
        acme_embed = shape.embedding_model("acme-embed", acme)
        configs = {
            "acme_own": shape.llm_config("Acme own", acme_finetune, acme),
            "beta_first": shape.llm_config("Beta first", acme_finetune, beta),
            "beta_second": shape.llm_config("Beta second", acme_finetune, beta),
            "beta_reuses_own_row": shape.llm_config("Beta reuse", acme_shared, beta),
            "beta_builtin": shape.llm_config("Beta builtin", builtin, beta),
            "beta_same_org": shape.llm_config("Beta same org", beta_shared, beta),
            "acme_embedding": shape.embedding_config("Acme embedding", acme_embed, acme),
            "beta_embedding": shape.embedding_config("Beta embedding", acme_embed, beta),
        }
        config_ids = {name: (type(config).__name__, config.pk) for name, config in configs.items()}

        owned_apps = _migrate(OWNED)

        def model_of(name):
            config_model, pk = config_ids[name]
            return owned_apps.get_model("ai_models", config_model).objects.get(pk=pk).model

        llm_models = owned_apps.get_model("ai_models", "LLMModel").objects
        beta_finetune = model_of("beta_first")
        assert (
            beta_finetune.org_id,
            beta_finetune.name,
            beta_finetune.llm_provider_id,
            beta_finetune.is_custom,
            beta_finetune.predefined,
            beta_finetune.is_visible,
            beta_finetune.description,
        ) == (beta.pk, "acme-finetune", shape.provider.pk, True, False, False, "Tuned by Acme")
        # Both of beta's configs on the foreign row share one new row.
        assert model_of("beta_second").pk == beta_finetune.pk
        assert llm_models.filter(name="acme-finetune").count() == 2
        assert model_of("acme_own").pk == acme_finetune.pk
        assert llm_models.get(pk=acme_finetune.pk).org_id == acme.pk
        # Beta already had a row of that name and provider: reused, none created.
        assert model_of("beta_reuses_own_row").pk == beta_shared.pk
        assert llm_models.filter(name="shared-name").count() == 2
        assert model_of("beta_builtin").pk == builtin.pk
        assert model_of("beta_same_org").pk == beta_shared.pk

        beta_embed = model_of("beta_embedding")
        assert (
            beta_embed.org_id,
            beta_embed.name,
            beta_embed.embedding_provider_id,
            beta_embed.is_custom,
        ) == (beta.pk, "acme-embed", shape.provider.pk, True)
        assert model_of("acme_embedding").pk == acme_embed.pk
    finally:
        _migrate_to_leaves()


@pytest.fixture
def _no_storage_calls(mocker):
    """Deleting an organization reaches MinIO/RustFS; stub both entry points."""
    mocker.patch(
        "tables.services.organization_deletion.get_storage_backend",
        return_value=mocker.MagicMock(list_all_objects=lambda *args, **kwargs: []),
    )
    mocker.patch(
        "rbac.governance.organizations.org_storage_provisioning_service.deprovision_for_organization"
    )


@pytest.mark.django_db(transaction=True)
def test_deleting_the_org_owning_the_model_keeps_the_other_orgs_configs(
    _no_storage_calls, django_user_model
):
    from ai_models.models import EmbeddingConfig, LLMConfig
    from rbac.governance.organizations import OrganizationManagementService

    try:
        shape = _LegacyShape(_migrate(BEFORE))
        acme, beta = shape.acme, shape.beta
        acme_finetune = shape.llm_model("acme-finetune", acme)
        acme_embed = shape.embedding_model("acme-embed", acme)
        acme_config = shape.llm_config("Acme own", acme_finetune, acme)
        beta_config = shape.llm_config("Beta on Acme", acme_finetune, beta)
        beta_embedding = shape.embedding_config("Beta on Acme", acme_embed, beta)
        _migrate_to_leaves()
        actor = django_user_model.objects.create_user(
            email="own-org-models-actor@x.com", password="StrongPass123!"
        )

        OrganizationManagementService().delete_organization(
            actor, acme.pk, verification_phrase="delete-Own Acme"
        )

        assert not LLMConfig.objects.filter(pk=acme_config.pk).exists()
        assert LLMConfig.objects.get(pk=beta_config.pk).model.org_id == beta.pk
        assert EmbeddingConfig.objects.get(pk=beta_embedding.pk).model.org_id == beta.pk
    finally:
        _migrate_to_leaves()
