import copy
import time

import pytest
from app.secret_decryption import decrypt_header_markers
from foundation.cryptographer import DecryptDataError

from tests.secret_sealing import agent_cryptographer, header_marker, seal


def test_replaces_marker_and_keeps_surrounding_text():
    headers = {"Authorization": f"Bearer {header_marker(seal('token-1'))}"}

    assert decrypt_header_markers(headers, agent_cryptographer()) == {
        "Authorization": "Bearer token-1"
    }


def test_tolerates_whitespace_inside_the_marker():
    headers = {"X-Key": f"epicstaff_secret(  {seal('token-1')}  )"}

    assert decrypt_header_markers(headers, agent_cryptographer()) == {"X-Key": "token-1"}


def test_replaces_several_markers_in_one_value():
    headers = {
        "X-Pair": f"user={header_marker(seal('alice'))};pass={header_marker(seal('hunter2'))}"
    }

    assert decrypt_header_markers(headers, agent_cryptographer()) == {
        "X-Pair": "user=alice;pass=hunter2"
    }


def test_replaces_markers_across_keys_and_keeps_other_values():
    headers = {
        "Authorization": f"Bearer {header_marker(seal('token-1'))}",
        "X-Api-Key": header_marker(seal("key-2")),
        "Accept": "application/json",
        "X-Retries": 3,
        "X-Flags": ["epicstaff_secret(not-a-string-value)"],
        "X-Empty": None,
    }

    assert decrypt_header_markers(headers, agent_cryptographer()) == {
        "Authorization": "Bearer token-1",
        "X-Api-Key": "key-2",
        "Accept": "application/json",
        "X-Retries": 3,
        "X-Flags": ["epicstaff_secret(not-a-string-value)"],
        "X-Empty": None,
    }


@pytest.mark.parametrize("headers", [None, {}])
def test_passes_none_and_empty_through(headers):
    assert decrypt_header_markers(headers, agent_cryptographer()) is headers


def test_returns_a_new_dict_and_leaves_input_untouched():
    headers = {
        "Authorization": f"Bearer {header_marker(seal('token-1'))}",
        "Accept": "application/json",
    }
    original = copy.deepcopy(headers)

    decrypted = decrypt_header_markers(headers, agent_cryptographer())

    assert headers == original
    assert decrypted is not headers
    unmarked = {"Accept": "application/json"}
    assert decrypt_header_markers(unmarked, agent_cryptographer()) is not unmarked


def test_undecryptable_marker_raises_without_leaking_header_text():
    forged = seal("token-1")[:-8] + "AAAAAAAA"
    headers = {"Authorization": f"Bearer {header_marker(forged)} tail-text"}

    with pytest.raises(DecryptDataError) as error:
        decrypt_header_markers(headers, agent_cryptographer())

    messages = [str(error.value), repr(error.value), str(error.value.__cause__)]
    for message in messages:
        assert forged not in message
        assert "Bearer" not in message
        assert "tail-text" not in message
        assert "Authorization" not in message


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("epicstaff_secret({sealed})", "token-1"),
        ("epicstaff_secret(\n {sealed} \t)", "token-1"),
        ("a=epicstaff_secret({sealed});b=epicstaff_secret( {sealed} )", "a=token-1;b=token-1"),
        ("epicstaff_secret({sealed}", "epicstaff_secret({sealed}"),
        ("epicstaff_secret()", "epicstaff_secret()"),
        ("epicstaff_secret(   )", "epicstaff_secret(   )"),
        ("epicstaff_secret(epicstaff_secret({sealed})", "epicstaff_secret(token-1"),
        ("epicstaff_secret( epicstaff_secret({sealed})", "epicstaff_secret( token-1"),
    ],
    ids=[
        "plain",
        "padded-newline-tab",
        "two-markers",
        "unclosed",
        "empty",
        "blank",
        "unclosed-right-before-closed",
        "unclosed-space-before-closed",
    ],
)
def test_marker_syntax_matches_the_producer(template, expected):
    sealed = seal("token-1")
    headers = {"X-Key": template.format(sealed=sealed)}

    assert decrypt_header_markers(headers, agent_cryptographer()) == {
        "X-Key": expected.format(sealed=sealed)
    }


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("epicstaff_secret(a" + " " * 50_000, id="name-then-spaces"),
        pytest.param("epicstaff_secret(" + " " * 50_000, id="spaces-only"),
        pytest.param("epicstaff_secret( " * 3_000, id="repeated-unclosed"),
    ],
)
def test_a_long_unclosed_marker_is_left_as_is_quickly(value):
    started = time.perf_counter()
    decrypted = decrypt_header_markers({"X-Key": value}, agent_cryptographer())

    assert time.perf_counter() - started < 1.0
    assert decrypted == {"X-Key": value}
