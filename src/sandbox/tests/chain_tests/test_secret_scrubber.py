"""The outbound half of secret delivery: a value the child was given never leaves it.

build_env keeps plaintext out of generated source on the way in. These tests cover
the way out -- the scrubber that rewrites stdout, stderr, and result_data before any
consumer, including this container's own log, can read them.
"""

import json

import pytest
from secret_scrubber import (
    MASK,
    MASK_SECRET_ENV_VAR,
    build_masking_values,
    masking_enabled,
    scrub,
)

SECRET_NAME = "STRIPE KEY"
SECRET_VALUE = "sk-live-must-not-escape-7a21"
SECRETS = {SECRET_NAME: SECRET_VALUE}


@pytest.fixture(autouse=True)
def masking_on_by_default(monkeypatch):
    """Start every test from an unset MASK_SECRET.

    Without this the suite would inherit whoever's shell it runs in: a developer
    with MASK_SECRET=false exported would see the masking tests fail for a reason
    that has nothing to do with the code. Tests that care about the switch set it
    themselves.
    """
    monkeypatch.delenv(MASK_SECRET_ENV_VAR, raising=False)


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


class TestMaskingEnabledDefaultsToOn:
    """Absent configuration must mask. A deployment that never heard of this
    variable is the common case and has to be the safe one.

    These cover the env parsing only. Whether the gate is honoured is asserted
    against the real handler in
    test_execute_code_handler_env.py::TestMaskSecretSwitchEndToEnd -- scrub() itself
    always masks, so testing the switch through it here would prove nothing.
    """

    def test_an_unset_variable_enables_masking(self):
        assert masking_enabled() is True

    def test_an_empty_value_enables_masking(self, monkeypatch):
        """`MASK_SECRET=` in an .env file reads as empty, not as false."""
        monkeypatch.setenv(MASK_SECRET_ENV_VAR, "")

        assert masking_enabled() is True

    @pytest.mark.parametrize("value", ["flase", "fasle", "maybe", "off?", "2", "-1"])
    def test_an_unrecognised_value_enables_masking(self, monkeypatch, value):
        """Fail-secure: only an explicit, correctly-spelled false disables masking.
        A typo must not silently start publishing credentials."""
        monkeypatch.setenv(MASK_SECRET_ENV_VAR, value)

        assert masking_enabled() is True


class TestMaskingEnabledParsesTheValue:
    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes", " true "])
    def test_a_truthy_value_enables_masking(self, monkeypatch, value):
        monkeypatch.setenv(MASK_SECRET_ENV_VAR, value)

        assert masking_enabled() is True

    @pytest.mark.parametrize(
        "value", ["false", "False", "FALSE", "0", "no", "off", "f", "n", " false "]
    )
    def test_a_falsey_value_disables_masking(self, monkeypatch, value):
        monkeypatch.setenv(MASK_SECRET_ENV_VAR, value)

        assert masking_enabled() is False

    def test_the_value_is_read_per_call_not_cached_at_import(self, monkeypatch):
        """Read from the environment on each call, so the setting reflects the
        running configuration rather than module load order -- which is also what
        lets these tests use monkeypatch.setenv instead of reimporting."""
        monkeypatch.setenv(MASK_SECRET_ENV_VAR, "true")
        assert masking_enabled() is True

        monkeypatch.setenv(MASK_SECRET_ENV_VAR, "false")
        assert masking_enabled() is False

        monkeypatch.setenv(MASK_SECRET_ENV_VAR, "true")
        assert masking_enabled() is True


class TestBuildMaskingValuesMasksTemporaryStorageCredentialsUnconditionally:
    """`ExecuteCodeHandler.handle` builds its masking set through
    `build_masking_values(secrets if mask_secrets else {}, {temp storage
    creds})` -- the temp-credential half is passed unconditionally,
    regardless of `MASK_SECRET`. These tests reproduce that exact call
    pattern rather than asserting on `build_masking_values` in isolation, so
    a future refactor of the call site is what these actually pin."""

    TEMP_ACCESS_KEY = "temp-ak-must-not-leak"
    TEMP_SECRET_KEY = "temp-sk-must-not-leak"

    def _masking_values(self, *, mask_secrets: bool, user_secrets: dict[str, str]):
        return build_masking_values(
            user_secrets if mask_secrets else {},
            {
                "STORAGE_ACCESS_KEY": self.TEMP_ACCESS_KEY,
                "STORAGE_SECRET_KEY": self.TEMP_SECRET_KEY,
            },
        )

    def test_temp_credentials_are_masked_when_mask_secret_is_true(self):
        values = self._masking_values(
            mask_secrets=True, user_secrets={"K": SECRET_VALUE}
        )
        scrubbed = scrub(
            text=f"{self.TEMP_ACCESS_KEY} {self.TEMP_SECRET_KEY} {SECRET_VALUE}",
            secrets=values,
        )

        assert self.TEMP_ACCESS_KEY not in scrubbed
        assert self.TEMP_SECRET_KEY not in scrubbed
        assert SECRET_VALUE not in scrubbed

    def test_temp_credentials_are_masked_even_when_mask_secret_is_false(self):
        """The most important case: MASK_SECRET=false is a documented opt-out
        for the developer's *own* secrets, never for temp MinIO credentials
        the code never legitimately needed to see in plaintext output."""
        values = self._masking_values(
            mask_secrets=False, user_secrets={"K": SECRET_VALUE}
        )
        scrubbed = scrub(
            text=f"{self.TEMP_ACCESS_KEY} {self.TEMP_SECRET_KEY} {SECRET_VALUE}",
            secrets=values,
        )

        assert self.TEMP_ACCESS_KEY not in scrubbed
        assert self.TEMP_SECRET_KEY not in scrubbed
        # The opt-out still applies to the user's own secret.
        assert SECRET_VALUE in scrubbed

    def test_temp_credentials_are_masked_with_no_user_secrets_at_all(self):
        """Regression guard: scrub()'s early `if not secrets: return text`
        must not short-circuit masking when `use_storage=True` but the
        execution declared no user secrets -- `build_masking_values` must
        make the combined dict non-empty by itself."""
        values = self._masking_values(mask_secrets=True, user_secrets={})
        scrubbed = scrub(
            text=f"{self.TEMP_ACCESS_KEY} {self.TEMP_SECRET_KEY}", secrets=values
        )

        assert self.TEMP_ACCESS_KEY not in scrubbed
        assert self.TEMP_SECRET_KEY not in scrubbed
        assert scrubbed.count(MASK) == 2

    def test_the_callers_original_secrets_dict_is_not_mutated(self):
        user_secrets = {"K": SECRET_VALUE}
        build_masking_values(user_secrets, {"STORAGE_ACCESS_KEY": self.TEMP_ACCESS_KEY})

        assert user_secrets == {"K": SECRET_VALUE}


class TestScrubIgnoresTheSwitch:
    """scrub() is unconditional by design: the gate lives at the call site in
    ExecuteCodeHandler.handle. Pinned so nobody re-adds the check here and leaves
    two places to reason about."""

    def test_it_still_masks_with_masking_disabled(self, monkeypatch):
        monkeypatch.setenv(MASK_SECRET_ENV_VAR, "false")

        assert scrub(text=SECRET_VALUE, secrets=SECRETS) == MASK
