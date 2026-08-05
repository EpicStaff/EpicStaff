"""The node's source code IS its secret declaration.

Nothing else in the platform decides which credentials a node may read: there is
no client field to forward, so no frontend involvement and nothing to spoof.
These tests pin what a static scan can and cannot see.
"""

from tables.services.secrets import scan_secret_names


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
        assert scan_secret_names(code=code) == ["STRIPE_KEY"]

    def test_direct_import_form(self):
        code = """
from epicstaff_secrets import get_secret


def main(**kwargs):
    return charge(api_key=get_secret("STRIPE_KEY"))
"""
        assert scan_secret_names(code=code) == ["STRIPE_KEY"]

    def test_module_attribute_form(self):
        code = """
import epicstaff_secrets


def main(**kwargs):
    return epicstaff_secrets.get_secret("SLACK_TOKEN")
"""
        assert scan_secret_names(code=code) == ["SLACK_TOKEN"]

    def test_several_names_in_first_seen_order(self):
        code = """
from epicstaff_secrets import get_secret


def main(**kwargs):
    a = get_secret("FIRST")
    b = get_secret("SECOND")
    c = get_secret("THIRD")
    return a, b, c
"""
        assert scan_secret_names(code=code) == ["FIRST", "SECOND", "THIRD"]

    def test_repeated_name_is_deduped(self):
        code = """
from epicstaff_secrets import get_secret


def main(**kwargs):
    return get_secret("SAME") + get_secret("SAME")
"""
        assert scan_secret_names(code=code) == ["SAME"]

    def test_nested_call_is_found(self):
        # A call inside a comprehension, inside a nested function, still counts.
        code = """
from epicstaff_secrets import get_secret


def main(**kwargs):
    def inner():
        return [get_secret("DEEP") for _ in range(1)]

    return inner()
"""
        assert scan_secret_names(code=code) == ["DEEP"]


class TestIgnoresWhatIsNotACall:
    def test_name_in_a_comment_is_ignored(self):
        """An AST walk cannot be fooled the way a regex over the source would be."""
        code = """
def main(**kwargs):
    # get_secret("COMMENTED_OUT")
    return 1
"""
        assert scan_secret_names(code=code) == []

    def test_name_inside_an_unrelated_string_is_ignored(self):
        code = """
def main(**kwargs):
    return 'call get_secret("IN_A_STRING") to read a credential'
"""
        assert scan_secret_names(code=code) == []

    def test_no_calls_at_all(self):
        assert scan_secret_names(code="def main(**kwargs):\n    return 1\n") == []

    def test_similarly_named_function_is_ignored(self):
        code = """
def main(**kwargs):
    return get_secret_id("NOT_OURS")
"""
        assert scan_secret_names(code=code) == []


class TestUnresolvableCases:
    def test_dynamic_name_yields_nothing(self):
        """A variable argument is invisible to a static scan. The call then fails
        inside the sandbox with SecretNotAvailableError, which lists the names
        that WERE injected — the informative place to fail."""
        code = """
from epicstaff_secrets import get_secret


def main(**kwargs):
    which = kwargs["which"]
    return get_secret(which)
"""
        assert scan_secret_names(code=code) == []

    def test_non_string_literal_yields_nothing(self):
        code = "def main(**kwargs):\n    return get_secret(42)\n"
        assert scan_secret_names(code=code) == []

    def test_no_arguments_yields_nothing(self):
        code = "def main(**kwargs):\n    return get_secret()\n"
        assert scan_secret_names(code=code) == []

    def test_dynamic_and_literal_mixed_keeps_the_literal(self):
        code = """
from epicstaff_secrets import get_secret


def main(**kwargs):
    return get_secret("KNOWN"), get_secret(kwargs["other"])
"""
        assert scan_secret_names(code=code) == ["KNOWN"]

    def test_syntax_error_returns_empty(self):
        """Unparseable code cannot execute either, so injecting nothing is right —
        and it must not raise, or a broken node would break session publishing."""
        assert scan_secret_names(code="def main(:\n  oops") == []

    def test_empty_code_returns_empty(self):
        assert scan_secret_names(code="") == []
