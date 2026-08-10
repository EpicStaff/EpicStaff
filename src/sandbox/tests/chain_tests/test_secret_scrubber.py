"""The outbound half of secret delivery: a value the child was given never leaves it.

build_env keeps plaintext out of generated source on the way in. These tests cover
the way out -- the scrubber that rewrites stdout, stderr, and result_data before any
consumer, including this container's own log, can read them.
"""

import json

from secret_scrubber import MASK, scrub

SECRET_NAME = "STRIPE KEY"
SECRET_VALUE = "sk-live-must-not-escape-7a21"
SECRETS = {SECRET_NAME: SECRET_VALUE}


class TestScrubbing:
    def test_a_value_in_the_middle_of_a_line_is_masked(self):
        scrubbed = scrub(text=f"token is {SECRET_VALUE} ok", secrets=SECRETS)

        assert scrubbed == f"token is {MASK} ok"

    def test_the_mask_does_not_disclose_the_secret_name(self):
        """The mask travels into stdout, the SSE stream, and the observation handed
        to the LLM. None of them need the name to see that something was withheld."""
        scrubbed = scrub(text=SECRET_VALUE, secrets=SECRETS)

        assert scrubbed == MASK
        assert SECRET_NAME not in scrubbed

    def test_every_occurrence_is_masked_not_only_the_first(self):
        scrubbed = scrub(text=f"{SECRET_VALUE}\nagain: {SECRET_VALUE}", secrets=SECRETS)

        assert SECRET_VALUE not in scrubbed
        assert scrubbed.count(MASK) == 2

    def test_text_without_a_secret_is_returned_unchanged(self):
        text = "processed 10 rows in 4.2s"

        assert scrub(text=text, secrets=SECRETS) == text


class TestLengthIsNotConsidered:
    """A secret is masked however short it is. Garbling surrounding text is a loud,
    self-correcting symptom; leaking the value is silent and permanent."""

    def test_a_single_character_value_is_masked(self):
        assert scrub(text="value is 7", secrets={"FLAG": "7"}) == f"value is {MASK}"

    def test_a_short_word_value_is_masked(self):
        assert scrub(text="mode=true", secrets={"MODE": "true"}) == f"mode={MASK}"

    def test_a_short_value_masks_incidental_matches(self):
        """The accepted cost of having no threshold, pinned so it is a documented
        trade rather than a surprise. The fix is not to store "1" as a credential."""
        scrubbed = scrub(text="processed 1 of 10 rows", secrets={"FLAG": "1"})

        assert scrubbed == f"processed {MASK} of {MASK}0 rows"

    def test_a_long_value_is_masked_the_same_way(self):
        assert scrub(text=SECRET_VALUE, secrets=SECRETS) == MASK


class TestRegexMetacharactersInValues:
    """The literal-vs-pattern switch is the actual risk in moving from str.replace
    to a compiled regex: a value containing regex syntax must still be matched as
    plain text, or scrubbing silently stops working for exactly the values most
    likely to appear in a real credential."""

    def test_a_value_containing_dot_star_is_matched_literally(self):
        value = "sk-live.*anything"

        assert scrub(text=value, secrets={"K": value}) == MASK

    def test_a_value_that_looks_like_a_character_class_is_matched_literally(self):
        value = "sk-live[0-9]+end"

        assert scrub(text=value, secrets={"K": value}) == MASK

    def test_a_value_containing_a_backslash_is_matched_literally(self):
        value = "sk-live\\d+token"

        assert scrub(text=value, secrets={"K": value}) == MASK

    def test_metacharacters_do_not_make_the_pattern_match_unrelated_text(self):
        """If '.' were left unescaped it would match any character, masking text
        that never contained the secret at all."""
        value = "sk-live.end"

        assert scrub(text="sk-liveXend", secrets={"K": value}) == "sk-liveXend"


class TestJsonEscapedForms:
    """result_data is the user's return value under json.dumps, so a value holding a
    quote, a backslash, or a non-ASCII character appears there only escaped."""

    def test_a_value_with_a_quote_and_a_backslash_is_masked_inside_json(self):
        value = 'sk-live-"quoted"-and\\slashed'
        payload = json.dumps({"token": value})

        scrubbed = scrub(text=payload, secrets={"K": value})

        assert value not in scrubbed
        assert json.dumps(value)[1:-1] not in scrubbed
        assert MASK in scrubbed

    def test_a_non_ascii_value_is_masked_inside_json(self):
        value = "sk-live-ключ-значение"
        payload = json.dumps({"token": value})

        scrubbed = scrub(text=payload, secrets={"K": value})

        assert json.dumps(value)[1:-1] not in scrubbed
        assert MASK in scrubbed

    def test_a_plain_value_is_still_masked_in_its_raw_form(self):
        payload = json.dumps({"token": SECRET_VALUE})

        assert SECRET_VALUE not in scrub(text=payload, secrets=SECRETS)


class TestOverlappingValues:
    """Longest-first replacement is load-bearing: masking a shorter value first would
    leave the remainder of a longer one sitting in the output beside the mask."""

    def test_no_remainder_of_the_longer_value_survives(self):
        short = "sk-live-shared"
        long = f"{short}-with-more-suffix"

        scrubbed = scrub(text=long, secrets={"SHORT": short, "LONG": long})

        assert scrubbed == MASK
        assert "-with-more-suffix" not in scrubbed

    def test_both_values_are_masked_when_both_appear(self):
        short = "sk-live-shared"
        long = f"{short}-with-more-suffix"

        scrubbed = scrub(
            text=f"{long} then {short}", secrets={"SHORT": short, "LONG": long}
        )

        assert scrubbed == f"{MASK} then {MASK}"

    def test_two_secrets_sharing_a_value_are_masked_once_not_twice(self):
        """Values are deduplicated, so the same literal is not replaced twice --
        which would otherwise mask an already-written mask."""
        scrubbed = scrub(
            text=SECRET_VALUE, secrets={"A": SECRET_VALUE, "B": SECRET_VALUE}
        )

        assert scrubbed == MASK


class TestPassThrough:
    def test_none_passes_through(self):
        """result_data is None whenever the run failed or wrote no result file."""
        assert scrub(text=None, secrets=SECRETS) is None

    def test_empty_text_passes_through(self):
        assert scrub(text="", secrets=SECRETS) == ""

    def test_no_secrets_leaves_text_untouched(self):
        text = f"nothing to hide {SECRET_VALUE}"

        assert scrub(text=text, secrets={}) == text

    def test_an_empty_value_is_ignored_rather_than_masking_everything(self):
        """The only value the scrubber skips, and not for its length: str.replace("")
        matches between every character, so an empty literal would replace the whole
        output with masks. Without this guard "abc" becomes MASK-a-MASK-b-MASK-c-MASK.
        """
        text = "processed 10 rows"

        assert scrub(text=text, secrets={"EMPTY": ""}) == text

    def test_an_empty_value_does_not_stop_a_real_one_being_masked(self):
        scrubbed = scrub(
            text=f"key {SECRET_VALUE}", secrets={"EMPTY": "", "REAL": SECRET_VALUE}
        )

        assert scrubbed == f"key {MASK}"
