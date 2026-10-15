"""A secret in the recycle bin keeps the links that point at it; a purge clears them."""

import pytest
from tables.models import LLMConfig, PythonCode, Secret
from tables.services.recycle_bin.restore_service import RestoreService
from tables.services.secrets.exceptions import SecretResolutionError
from tables.services.secrets.secret_resolver import secret_resolver
from tables.services.secrets.secret_service import secret_service

pytestmark = pytest.mark.django_db


@pytest.fixture
def secret(default_org):
    return secret_service.create(text="sk-live", org=default_org, name="OPENAI_KEY")


@pytest.fixture
def secret_in_use(llm_config, secret):
    """The secret as an LLM config's API key and in a Python code's declaration."""
    llm_config.api_key_secret = secret
    llm_config.save()
    python_code = PythonCode.objects.create(code="def main(): pass")
    python_code.secrets.add(secret)
    return secret


def _declares(secret: Secret) -> bool:
    # The through table directly: python_code.secrets.all() reads Secret.objects,
    # which hides binned rows.
    return PythonCode.secrets.through.objects.filter(secret_id=secret.pk).exists()


def test_a_binned_secret_keeps_its_links_and_doesnt_resolve(llm_config, secret_in_use):
    secret_in_use.delete()

    llm_config.refresh_from_db()
    assert llm_config.api_key_secret_id == secret_in_use.pk
    assert _declares(secret_in_use)
    with pytest.raises(SecretResolutionError):
        secret_resolver.resolve(secret_id=secret_in_use.pk, org_id=secret_in_use.org_id)


def test_no_resolver_path_decrypts_a_binned_secret(secret):
    # Every consumer (LLM, embedding, realtime, MCP, ngrok, Twilio, Telegram, code)
    # decrypts through SecretResolver, and these are its only lookups.
    secret.delete()

    # These two skip a missing secret rather than raise: it's simply left out.
    assert secret_resolver.resolve_many(secret_ids=[secret.pk], org_id=secret.org_id) == {}
    assert secret_resolver.resolve_named(names=[secret.name], org_id=secret.org_id) == {}


def test_a_restored_secret_resolves_again_through_the_same_links(llm_config, secret_in_use):
    secret_in_use.delete()

    RestoreService.restore(Secret.all_objects.get(pk=secret_in_use.pk))

    llm_config.refresh_from_db()
    assert llm_config.api_key_secret_id == secret_in_use.pk
    assert _declares(secret_in_use)
    assert (
        secret_resolver.resolve(secret_id=secret_in_use.pk, org_id=secret_in_use.org_id)
        == "sk-live"
    )


def test_a_purge_clears_the_links_and_keeps_the_rows_that_used_it(llm_config, secret_in_use):
    secret_in_use.delete()

    Secret.all_objects.get(pk=secret_in_use.pk).purge()

    llm_config.refresh_from_db()
    assert llm_config.api_key_secret_id is None
    assert LLMConfig.objects.filter(pk=llm_config.pk).exists()
    assert not _declares(secret_in_use)
