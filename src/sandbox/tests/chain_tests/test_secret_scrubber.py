"""The scrubber that removes injected secret values from an execution's output.

Whether the handler actually runs it on every stream, and honours MASK_SECRET, is
asserted end to end in test_execute_code_handler_env.py and
test_execute_code_handler_timeout.py.
"""

import json

import pytest
from secret_scrubber import MASK, build_masking_values, scrub

SECRET = "sk-live-must-not-escape-7a21"
SHORT = "sk-live-shared"
LONG = f"{SHORT}-with-more-suffix"


@pytest.mark.parametrize(
    ("text", "secrets", "expected"),
    [
        (f"token is {SECRET} ok", {"STRIPE KEY": SECRET}, f"token is {MASK} ok"),
        # The mask names nothing: it travels to stdout, SSE and the LLM's observation.
        (SECRET, {"STRIPE KEY": SECRET}, MASK),
        (f"{SECRET}\nagain: {SECRET}", {"K": SECRET}, f"{MASK}\nagain: {MASK}"),
        ("processed 10 rows in 4.2s", {"K": SECRET}, "processed 10 rows in 4.2s"),
        # No length threshold: garbling output is loud and self-correcting, a leak is not.
        ("value is 7", {"FLAG": "7"}, f"value is {MASK}"),
        ("mode=true", {"MODE": "true"}, f"mode={MASK}"),
        ("processed 1 of 10 rows", {"FLAG": "1"}, f"processed {MASK} of {MASK}0 rows"),
        # Values are literals, never regex syntax.
        ("sk-live.*anything", {"K": "sk-live.*anything"}, MASK),
        ("sk-live[0-9]+end", {"K": "sk-live[0-9]+end"}, MASK),
        ("sk-live\\d+token", {"K": "sk-live\\d+token"}, MASK),
        ("sk-liveXend", {"K": "sk-live.end"}, "sk-liveXend"),
        # Longest first, so no remainder of a longer value survives beside the mask.
        (LONG, {"SHORT": SHORT, "LONG": LONG}, MASK),
        (f"{LONG} then {SHORT}", {"SHORT": SHORT, "LONG": LONG}, f"{MASK} then {MASK}"),
        # A shared value is masked once, not re-masked inside the mask.
        (SECRET, {"A": SECRET, "B": SECRET}, MASK),
        # An empty value would match between every character.
        ("processed 10 rows", {"EMPTY": ""}, "processed 10 rows"),
        (f"key {SECRET}", {"EMPTY": "", "REAL": SECRET}, f"key {MASK}"),
        (f"nothing to hide {SECRET}", {}, f"nothing to hide {SECRET}"),
        # result_data is None whenever the run failed or wrote no result file.
        (None, {"K": SECRET}, None),
        ("", {"K": SECRET}, ""),
    ],
)
def test_scrub(text, secrets, expected):
    assert scrub(text=text, secrets=secrets) == expected


@pytest.mark.parametrize(
    "value",
    ['sk-live-"quoted"-and\\slashed', "sk-live-ключ-значение", SECRET],
    ids=["quote-and-backslash", "non-ascii", "plain"],
)
def test_a_value_is_masked_in_its_json_escaped_form(value):
    """result_data is the return value under json.dumps, so a value appears there escaped."""
    payload = json.dumps({"token": value})

    scrubbed = scrub(text=payload, secrets={"K": value})

    assert value not in scrubbed
    assert json.dumps(value)[1:-1] not in scrubbed
    assert MASK in scrubbed


def test_masking_values_never_leak_into_the_secrets_the_code_receives():
    """The user's secrets dict becomes EPICSTAFF_SECRETS for the executed code, so the
    temporary storage credentials must not be added to it."""
    user_secrets = {"K": SECRET}

    masking_values = build_masking_values(user_secrets, {"STORAGE_ACCESS_KEY": "temp-ak"})

    assert user_secrets == {"K": SECRET}
    assert masking_values == {"K": SECRET, "STORAGE_ACCESS_KEY": "temp-ak"}
