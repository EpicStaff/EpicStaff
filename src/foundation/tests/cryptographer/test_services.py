import subprocess
import sys
import time
from base64 import urlsafe_b64decode

import pytest

from foundation.cryptographer import (
    DecryptDataError,
    EncodeDataError,
    EncryptDataError,
    FernetRotatedCryptographer,
    RotateDataError,
)

INFO = b"test.cryptographer.v1"
MAIN_KEY = "main-key"
RETIRED_KEY = "retired-key"

PLAINTEXT = "sk-some-provider-api-key"
NOT_A_TOKEN = ["", "not-a-token", "Z3JiYmVyaXNo", "gAAAAABneverminetheres"]  # gitleaks:allow


def build(main_key=MAIN_KEY, other_keys=(), **kwargs):
    return FernetRotatedCryptographer(
        main_key=main_key, other_keys=other_keys, hkdf_info=INFO, **kwargs
    )


def token_timestamp(token: str) -> int:
    """The creation time Fernet stores in the token, readable without any key."""
    return int.from_bytes(urlsafe_b64decode(token)[1:9], "big")


def test_round_trip_returns_the_original_text():
    cryptographer = build()
    assert cryptographer.decrypt(cryptographer.encrypt(PLAINTEXT)) == PLAINTEXT


def test_encrypting_the_same_text_twice_gives_different_tokens():
    cryptographer = build()
    assert cryptographer.encrypt(PLAINTEXT) != cryptographer.encrypt(PLAINTEXT)


def test_text_written_by_a_retired_key_still_reads():
    stale = build(main_key=RETIRED_KEY).encrypt(PLAINTEXT)
    assert build(other_keys=[RETIRED_KEY]).decrypt(stale) == PLAINTEXT


def test_encryption_uses_the_main_key():
    token = build(other_keys=[RETIRED_KEY]).encrypt(PLAINTEXT)
    assert build().decrypt(token) == PLAINTEXT


def test_a_key_outside_the_set_cannot_read_the_token():
    token = build().encrypt(PLAINTEXT)
    with pytest.raises(DecryptDataError):
        build(main_key="someone-elses-key").decrypt(token)


def test_the_same_keys_under_a_different_info_derive_a_different_key():
    token = build().encrypt(PLAINTEXT)
    other_domain = FernetRotatedCryptographer(main_key=MAIN_KEY, hkdf_info=b"other.domain.v1")
    with pytest.raises(DecryptDataError):
        other_domain.decrypt(token)


@pytest.mark.parametrize("data", NOT_A_TOKEN)
def test_decrypting_something_that_is_not_a_token_fails(data):
    with pytest.raises(DecryptDataError):
        build().decrypt(data)


def test_rotation_moves_the_text_onto_the_main_key():
    stale = build(main_key=RETIRED_KEY).encrypt(PLAINTEXT)
    cryptographer = build(other_keys=[RETIRED_KEY])

    rotated = cryptographer.rotate(stale)

    assert build().decrypt(rotated) == PLAINTEXT


def test_rotation_keeps_the_creation_time(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1_000_000)
    stale = build(main_key=RETIRED_KEY).encrypt(PLAINTEXT)
    monkeypatch.setattr(time, "time", lambda: 1_086_400)

    rotated = build(other_keys=[RETIRED_KEY]).rotate(stale)

    assert token_timestamp(rotated) == 1_000_000


@pytest.mark.parametrize("data", NOT_A_TOKEN)
def test_rotating_something_no_key_can_read_fails(data):
    with pytest.raises(RotateDataError):
        build().rotate(data)


def test_text_on_the_main_key_reports_as_rotated():
    cryptographer = build(other_keys=[RETIRED_KEY])
    assert cryptographer.is_rotated(cryptographer.encrypt(PLAINTEXT)) is True


def test_text_on_a_retired_key_reports_as_not_rotated():
    stale = build(main_key=RETIRED_KEY).encrypt(PLAINTEXT)
    assert build(other_keys=[RETIRED_KEY]).is_rotated(stale) is False


@pytest.mark.parametrize("data", NOT_A_TOKEN)
def test_something_that_is_not_a_token_reports_as_not_rotated(data):
    assert build().is_rotated(data) is False


@pytest.mark.parametrize("size", [1, 8191, 8192])
def test_text_up_to_the_default_limit_is_encrypted(size):
    cryptographer = build()
    text = "a" * size
    assert cryptographer.decrypt(cryptographer.encrypt(text)) == text


@pytest.mark.parametrize("size", [8193, 9000])
def test_text_over_the_default_limit_is_refused(size):
    with pytest.raises(EncryptDataError):
        build().encrypt("a" * size)


def test_the_limit_counts_bytes_not_characters():
    """Four-byte characters hit a 16-byte limit at the fifth one, not the seventeenth."""
    cryptographer = build(max_data_size=16)
    assert cryptographer.decrypt(cryptographer.encrypt("𐍈" * 4)) == "𐍈" * 4
    with pytest.raises(EncryptDataError):
        cryptographer.encrypt("𐍈" * 5)


def test_text_that_is_not_encodable_as_utf8_is_refused():
    with pytest.raises(EncodeDataError):
        build().encrypt("\ud800")


def test_importing_the_package_does_not_require_the_cryptography_dependency():
    """`cryptography` is an optional extra, so nothing may import it at module level."""
    probe = (
        "import sys;"
        "import foundation.cryptographer as package;"
        "assert 'cryptography' not in sys.modules, 'imported at module level';"
        "package.FernetRotatedCryptographer('k', hkdf_info=b'i').encrypt('v');"
        "assert 'cryptography' in sys.modules, 'never imported at all'"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
