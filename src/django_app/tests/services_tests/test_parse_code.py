"""What a static parse of node code can and cannot see.

This is the *check* side of the allow-list, not the declaration: the declaration is
PythonCode.secrets, written through `secret_ids`. Callers compare the two as sets
(``undeclared = parsed - declared``), so these tests assert set contents and never
ordering — order lives in the display layer, where names get sorted.
"""

import pytest

from tables.services.secrets import parse_secret_names

IMPORT = "from epicstaff_secrets import get_secret\n\n"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        # wrap_code puts get_secret in the execution namespace (like DotDict), so
        # node code normally carries no import line; the scan matches the call.
        pytest.param('def main(**kwargs):\n    return charge(api_key=get_secret("STRIPE_KEY"))\n', {"STRIPE_KEY"}, id="no-import"),
        pytest.param(IMPORT + 'def main(**kwargs):\n    return get_secret("STRIPE_KEY")\n', {"STRIPE_KEY"}, id="direct-import"),
        pytest.param('import epicstaff_secrets\n\ndef main(**kwargs):\n    return epicstaff_secrets.get_secret("SLACK_TOKEN")\n', {"SLACK_TOKEN"}, id="module-attribute"),
        pytest.param(IMPORT + 'def main(**kwargs):\n    return get_secret("THIRD"), get_secret("FIRST"), get_secret("SECOND")\n', {"FIRST", "SECOND", "THIRD"}, id="every-name"),
        pytest.param(IMPORT + 'def main(**kwargs):\n    return get_secret("SAME") + get_secret("SAME")\n', {"SAME"}, id="repeated-once"),
        pytest.param(IMPORT + 'def main(**kwargs):\n    def inner():\n        return [get_secret("DEEP") for _ in range(1)]\n    return inner()\n', {"DEEP"}, id="nested-call"),
        # An AST walk cannot be fooled the way a regex over the source would be.
        pytest.param('def main(**kwargs):\n    # get_secret("COMMENTED_OUT")\n    return 1\n', set(), id="comment"),
        pytest.param('def main(**kwargs):\n    return \'call get_secret("IN_A_STRING")\'\n', set(), id="inside-a-string"),
        pytest.param("def main(**kwargs):\n    return 1\n", set(), id="no-calls"),
        pytest.param('def main(**kwargs):\n    return get_secret_id("NOT_OURS")\n', set(), id="similar-name"),
        # A variable argument is invisible to a static parse; the call then fails in the
        # sandbox with SecretNotAvailableError, which lists what WAS injected.
        pytest.param(IMPORT + 'def main(**kwargs):\n    return get_secret(kwargs["which"])\n', set(), id="dynamic-name"),
        pytest.param("def main(**kwargs):\n    return get_secret(42)\n", set(), id="non-string"),
        pytest.param("def main(**kwargs):\n    return get_secret()\n", set(), id="no-arguments"),
        pytest.param(IMPORT + 'def main(**kwargs):\n    return get_secret("KNOWN"), get_secret(kwargs["other"])\n', {"KNOWN"}, id="dynamic-and-literal"),
        # Unparseable code cannot run either; it must not raise, or a broken node
        # would break session publishing.
        pytest.param("def main(:\n  oops", set(), id="syntax-error"),
        pytest.param("", set(), id="empty"),
    ],
)
def test_parse_secret_names(code, expected):
    assert parse_secret_names(code=code) == expected
