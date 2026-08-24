"""The mapper injects the credential Django sent, and refuses to guess.

Every embedder in this service does `api_key or os.getenv(...)`, and
_set_embedder_config falls back to a default OpenAI embedder on any exception, so
a missing credential would otherwise be served by the container's ambient env key
-- another tenant's account, or an unexplained provider 401.

"Is a credential expected?" comes from the api_key_secret_configured flag that
storage reads off the api_key_secret_id column, never from whether a credential
happened to arrive. Deriving it from the credential would make the guard
tautological and leave the dropped-credential case silent.
"""

import pytest

from services.credential_mapper import (
    CONFIGURED_FLAG,
    MissingCredentialError,
    apply_credential,
)


def _config(*, configured: bool):
    return {
        "model_name": "text-embedding-3-small",
        "provider": "openai",
        CONFIGURED_FLAG: configured,
    }


def test_the_credential_is_injected():
    config = apply_credential(
        config=_config(configured=True),
        api_key="sk-live",
        context="naive_rag_id=2 embedder",
    )
    assert config["api_key"] == "sk-live"


def test_a_configured_credential_that_did_not_arrive_raises():
    """The real defect this guards: the RAG has a secret, none was delivered."""
    with pytest.raises(MissingCredentialError) as exc:
        apply_credential(
            config=_config(configured=True),
            api_key=None,
            context="naive_rag_id=2 embedder",
        )
    assert "naive_rag_id=2 embedder" in str(exc.value)


def test_an_empty_credential_is_treated_as_absent():
    with pytest.raises(MissingCredentialError):
        apply_credential(
            config=_config(configured=True),
            api_key="",
            context="graph_rag_id=1 llm",
        )


def test_no_configured_secret_leaves_api_key_unset():
    """The ambient-env path stays available for local development."""
    config = apply_credential(
        config=_config(configured=False),
        api_key=None,
        context="naive_rag_id=3 embedder",
    )
    assert config.get("api_key") is None


def test_a_missing_flag_is_treated_as_not_configured():
    config = apply_credential(
        config={"model_name": "m", "provider": "openai"},
        api_key=None,
        context="naive_rag_id=4 embedder",
    )
    assert config.get("api_key") is None


def test_the_flag_never_reaches_the_provider_config():
    """The flag is ours; passing it on to a provider client would be junk."""
    config = apply_credential(
        config=_config(configured=True),
        api_key="sk-live",
        context="naive_rag_id=2 embedder",
    )
    assert CONFIGURED_FLAG not in config


def test_the_caller_s_dict_is_not_mutated():
    original = _config(configured=True)
    apply_credential(
        config=original,
        api_key="sk-live",
        context="naive_rag_id=2 embedder",
    )
    assert "api_key" not in original
    assert CONFIGURED_FLAG in original


def test_the_error_message_never_contains_the_credential():
    with pytest.raises(MissingCredentialError) as exc:
        apply_credential(
            config=_config(configured=True),
            api_key=None,
            context="naive_rag_id=2 embedder",
        )
    assert "sk-" not in str(exc.value)
