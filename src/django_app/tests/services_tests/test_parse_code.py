"""What a static parse of node code can and cannot see.

This is the *check* side of the allow-list, not the declaration: the declaration is
PythonCode.secrets, written through `secret_ids`. Callers compare the two as sets
(``undeclared = parsed - declared``), so these tests assert set contents and never
ordering — order lives in the display layer, where names get sorted.
"""

from tables.services.secrets import parse_secret_names


class TestFindsDeclaredNames:
    def test_no_import_at_all_is_the_normal_form(self):
        """wrap_code puts get_secret in the execution namespace, the same way it
        already provides DotDict, so node code carries no import line. The scan
        matches the call and never an import, which is what lets the two be
        independent -- but it is the documented form, so it is pinned here."""
        code = """
def main(**kwargs):
    return charge(api_key=get_secret("STRIPE_KEY"))
"""
        assert parse_secret_names(code=code) == {"STRIPE_KEY"}

    def test_direct_import_form(self):
        code = """
from epicstaff_secrets import get_secret


def main(**kwargs):
    return charge(api_key=get_secret("STRIPE_KEY"))
"""
        assert parse_secret_names(code=code) == {"STRIPE_KEY"}

    def test_module_attribute_form(self):
        code = """
import epicstaff_secrets


def main(**kwargs):
    return epicstaff_secrets.get_secret("SLACK_TOKEN")
"""
        assert parse_secret_names(code=code) == {"SLACK_TOKEN"}

    def test_every_name_in_the_file_is_found(self):
        """All of them, and position is irrelevant — the result is a set because
        every caller subtracts it from the declared set."""
        code = """
from epicstaff_secrets import get_secret


def main(**kwargs):
    a = get_secret("THIRD")
    b = get_secret("FIRST")
    c = get_secret("SECOND")
    return a, b, c
"""
        assert parse_secret_names(code=code) == {"FIRST", "SECOND", "THIRD"}

    def test_repeated_name_appears_once(self):
        code = """
from epicstaff_secrets import get_secret


def main(**kwargs):
    return get_secret("SAME") + get_secret("SAME")
"""
        assert parse_secret_names(code=code) == {"SAME"}

    def test_nested_call_is_found(self):
        # A call inside a comprehension, inside a nested function, still counts.
        code = """
from epicstaff_secrets import get_secret


def main(**kwargs):
    def inner():
        return [get_secret("DEEP") for _ in range(1)]

    return inner()
"""
        assert parse_secret_names(code=code) == {"DEEP"}


class TestIgnoresWhatIsNotACall:
    def test_name_in_a_comment_is_ignored(self):
        """An AST walk cannot be fooled the way a regex over the source would be."""
        code = """
def main(**kwargs):
    # get_secret("COMMENTED_OUT")
    return 1
"""
        assert parse_secret_names(code=code) == set()

    def test_name_inside_an_unrelated_string_is_ignored(self):
        code = """
def main(**kwargs):
    return 'call get_secret("IN_A_STRING") to read a credential'
"""
        assert parse_secret_names(code=code) == set()

    def test_no_calls_at_all(self):
        assert parse_secret_names(code="def main(**kwargs):\n    return 1\n") == set()

    def test_similarly_named_function_is_ignored(self):
        code = """
def main(**kwargs):
    return get_secret_id("NOT_OURS")
"""
        assert parse_secret_names(code=code) == set()


class TestUnresolvableCases:
    def test_dynamic_name_yields_nothing(self):
        """A variable argument is invisible to a static parse. The call then fails
        inside the sandbox with SecretNotAvailableError, which lists the names
        that WERE injected — the informative place to fail."""
        code = """
from epicstaff_secrets import get_secret


def main(**kwargs):
    which = kwargs["which"]
    return get_secret(which)
"""
        assert parse_secret_names(code=code) == set()

    def test_non_string_literal_yields_nothing(self):
        code = "def main(**kwargs):\n    return get_secret(42)\n"
        assert parse_secret_names(code=code) == set()

    def test_no_arguments_yields_nothing(self):
        code = "def main(**kwargs):\n    return get_secret()\n"
        assert parse_secret_names(code=code) == set()

    def test_dynamic_and_literal_mixed_keeps_the_literal(self):
        code = """
from epicstaff_secrets import get_secret


def main(**kwargs):
    return get_secret("KNOWN"), get_secret(kwargs["other"])
"""
        assert parse_secret_names(code=code) == {"KNOWN"}

    def test_syntax_error_returns_empty(self):
        """Unparseable code cannot execute either, so injecting nothing is right —
        and it must not raise, or a broken node would break session publishing."""
        assert parse_secret_names(code="def main(:\n  oops") == set()

    def test_empty_code_returns_empty(self):
        assert parse_secret_names(code="") == set()
