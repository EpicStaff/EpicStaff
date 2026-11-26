"""Behavior of the outbound secret scrubber.

It is a safety net against accidental disclosure, not a boundary. The tests cover the
shapes a value can take on the way out -- raw and JSON-escaped -- and the deliberate
decision to mask even a one-character value.
"""

import json

from worker.application.secret_scrubber import MASK, scrub


def test_a_secret_value_is_masked():
    assert scrub(text="token is s3cret", values=["s3cret"]) == f"token is {MASK}"


def test_every_occurrence_is_masked():
    assert scrub(text="s3cret s3cret", values=["s3cret"]) == f"{MASK} {MASK}"


def test_several_secrets_are_masked_in_one_pass():
    text = "user=alice pass=hunter2"
    values = ["alice", "hunter2"]

    assert scrub(text=text, values=values) == f"user={MASK} pass={MASK}"


def test_the_json_escaped_form_of_a_value_is_masked_too():
    value = 'line1\nline2 "quoted"'
    escaped = json.dumps(value)[1:-1]

    assert scrub(text=f"dumped: {escaped}", values=[value]) == f"dumped: {MASK}"


def test_an_empty_secret_value_is_ignored():
    assert scrub(text="nothing to hide", values=[""]) == "nothing to hide"


def test_the_longer_of_two_overlapping_values_wins():
    values = ["s3cret", "s3cret-extended"]

    assert scrub(text="value is s3cret-extended", values=values) == f"value is {MASK}"


def test_a_one_character_secret_masks_every_occurrence_of_that_character():
    # Deliberate: garbled output is a loud symptom, a leaked value is silent.
    assert scrub(text="a b a", values=["a"]) == f"{MASK} b {MASK}"


def test_no_text_returns_no_text():
    assert scrub(text=None, values=["s3cret"]) is None


def test_empty_text_is_returned_unchanged():
    assert scrub(text="", values=["s3cret"]) == ""


def test_no_secrets_leaves_the_text_alone():
    assert scrub(text="token is s3cret", values=[]) == "token is s3cret"


def test_only_empty_secrets_leaves_the_text_alone():
    assert scrub(text="token is s3cret", values=["", ""]) == "token is s3cret"


def test_a_regex_metacharacter_in_a_value_is_matched_literally():
    assert scrub(text="key is a.c", values=["a.c"]) == f"key is {MASK}"
    assert scrub(text="key is abc", values=["a.c"]) == "key is abc"
