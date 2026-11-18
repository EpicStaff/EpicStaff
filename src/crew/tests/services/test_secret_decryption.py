import pytest
from foundation.cryptographer import FernetRotatedCryptographer
from src.crew.services.secret_decryption import (
    SecretDecryptionError,
    decrypt_llm_data,
    decrypt_system_one_config,
)
from src.shared.models.ai_providers import LLMConfigData, LLMData
from src.shared.models.system_one import SystemOneConfigData
from tests.secrets_cryptographer import TEST_SECRETS_CRYPTOGRAPHER

seal = TEST_SECRETS_CRYPTOGRAPHER.encrypt

# Sealed before a key rotation: the current cryptographer holds this key as a previous one.
ROTATED_CRYPTOGRAPHER = FernetRotatedCryptographer(
    "new-transport-key", ["test-transport-key"], hkdf_info=b"epicstaff.secrets.transport.test"
)

BROKEN_TOKEN = "gAAAAABroken-token"


def llm_data(api_key: str | None = None, extra_headers: dict | None = None) -> LLMData:
    return LLMData(
        provider="openai",
        config=LLMConfigData(model="gpt-4o-mini", api_key=api_key, extra_headers=extra_headers),
    )


@pytest.mark.parametrize(
    ("sealed_api_key", "expected_api_key"),
    [
        pytest.param(seal("sk-plain"), "sk-plain", id="sealed"),
        pytest.param(None, None, id="no-key"),
        pytest.param("", "", id="empty-key-means-no-key"),
    ],
)
def test_llm_api_key_is_decrypted(sealed_api_key, expected_api_key):
    decrypted = decrypt_llm_data(llm_data(api_key=sealed_api_key), TEST_SECRETS_CRYPTOGRAPHER)

    assert decrypted.config.api_key == expected_api_key


def test_value_sealed_with_a_previous_key_still_decrypts():
    decrypted = decrypt_llm_data(llm_data(api_key=seal("sk-plain")), ROTATED_CRYPTOGRAPHER)

    assert decrypted.config.api_key == "sk-plain"


@pytest.mark.parametrize(
    ("sealed_headers", "expected_headers"),
    [
        pytest.param(
            {"Authorization": f"Bearer epicstaff_secret({seal('token')})"},
            {"Authorization": "Bearer token"},
            id="marker-inside-a-value",
        ),
        pytest.param(
            {"X-Auth": f"epicstaff_secret({seal('a')}):epicstaff_secret( {seal('b')} )"},
            {"X-Auth": "a:b"},
            id="two-markers-in-one-value",
        ),
        pytest.param({"X-Team": "core"}, {"X-Team": "core"}, id="plain-value-kept"),
        pytest.param({}, {}, id="empty"),
        pytest.param(None, None, id="no-headers"),
    ],
)
def test_header_markers_are_decrypted(sealed_headers, expected_headers):
    decrypted = decrypt_llm_data(
        llm_data(extra_headers=sealed_headers), TEST_SECRETS_CRYPTOGRAPHER
    )

    assert decrypted.config.extra_headers == expected_headers


def test_the_sealed_original_is_left_unchanged():
    sealed_api_key = seal("sk-plain")
    sealed_header = f"Bearer epicstaff_secret({seal('token')})"
    original = llm_data(api_key=sealed_api_key, extra_headers={"Authorization": sealed_header})

    decrypt_llm_data(original, TEST_SECRETS_CRYPTOGRAPHER)

    assert original.config.api_key == sealed_api_key
    assert original.config.extra_headers == {"Authorization": sealed_header}


@pytest.mark.parametrize(
    ("broken_llm_data", "expected_field"),
    [
        pytest.param(llm_data(api_key=BROKEN_TOKEN), "api_key", id="api-key"),
        pytest.param(
            llm_data(extra_headers={"X-Auth": f"epicstaff_secret({BROKEN_TOKEN})"}),
            "extra_headers",
            id="header-marker",
        ),
    ],
)
def test_undecryptable_value_names_the_field_and_hides_the_value(broken_llm_data, expected_field):
    with pytest.raises(SecretDecryptionError) as raised:
        decrypt_llm_data(broken_llm_data, TEST_SECRETS_CRYPTOGRAPHER)

    assert str(raised.value) == f"{expected_field} could not be decrypted."


def test_system_one_config_key_and_its_llm_config_key_are_both_decrypted():
    config = SystemOneConfigData(
        id=1,
        provider="llm",
        api_key=seal("s1-plain"),
        llm_data=llm_data(api_key=seal("llm-plain")),
    )

    decrypted = decrypt_system_one_config(config, TEST_SECRETS_CRYPTOGRAPHER)

    assert decrypted.api_key == "s1-plain"
    assert decrypted.llm_data.config.api_key == "llm-plain"


def test_system_one_config_without_llm_config_decrypts_its_own_key():
    config = SystemOneConfigData(id=1, provider="openai", api_key=seal("s1-plain"))

    decrypted = decrypt_system_one_config(config, TEST_SECRETS_CRYPTOGRAPHER)

    assert decrypted.api_key == "s1-plain"
    assert decrypted.llm_data is None
