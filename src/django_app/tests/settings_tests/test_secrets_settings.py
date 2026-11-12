"""The at-rest encryption keys and the transport keys django_app reads from the environment.

Invariant, the same for both pairs: SECRETS_ENCRYPTION_KEY and SECRETS_TRANSPORT_KEY are
required, and one shorter than 12 characters stops django_app from starting without echoing
the value. SECRETS_ENCRYPTION_PREVIOUS_KEYS and SECRETS_TRANSPORT_PREVIOUS_KEYS are
comma-separated lists read into a tuple; `none` or an empty value lists no key.
"""

import importlib
from collections.abc import Callable, Iterator
from types import ModuleType

import django_app.settings.secrets as secrets_settings
import pytest
from django.core.exceptions import ImproperlyConfigured
from django_app.settings import env
from src.shared.envtools import EnvironmentBlankError, EnvironmentNotFoundError

KEY_PAIRS = [
    ("SECRETS_ENCRYPTION_KEY", "SECRETS_ENCRYPTION_PREVIOUS_KEYS"),
    ("SECRETS_TRANSPORT_KEY", "SECRETS_TRANSPORT_PREVIOUS_KEYS"),
]
VARIABLES = tuple(name for pair in KEY_PAIRS for name in pair)
VALID_KEY = "twelve-chars"


@pytest.fixture(params=KEY_PAIRS, ids=["encryption", "transport"])
def key_pair(request) -> tuple[str, str]:
    """The (key, previous keys) variable names under test."""
    return request.param


@pytest.fixture
def load_settings(key_pair) -> Iterator[Callable[[str | None, str], ModuleType]]:
    """Re-run the settings module against the given values of the `key_pair` variables.

    The module computes its values at import, from the `env` the settings package read
    once, so the test edits that `env` and reloads the module. The original values are
    put back and the module reloaded again, so later tests see the real settings.
    """
    key_variable, previous_keys_variable = key_pair
    original = {name: env._envs.get(name) for name in VARIABLES}

    def _load(key: str | None, previous_keys: str = "none") -> ModuleType:
        if key is None:
            env._envs.pop(key_variable, None)
        else:
            env._envs[key_variable] = key
        env._envs[previous_keys_variable] = previous_keys
        return importlib.reload(secrets_settings)

    yield _load

    for name, value in original.items():
        if value is None:
            env._envs.pop(name, None)
        else:
            env._envs[name] = value
    importlib.reload(secrets_settings)


def test_key_of_twelve_characters_is_accepted(load_settings, key_pair):
    module = load_settings(VALID_KEY)

    assert getattr(module, key_pair[0]) == VALID_KEY


def test_key_of_eleven_characters_stops_startup_without_echoing_it(load_settings, key_pair):
    short_key = "eleven-char"

    with pytest.raises(ImproperlyConfigured) as raised:
        load_settings(short_key)

    message = str(raised.value)
    assert f"{key_pair[0]} must be at least 12 characters" in message
    assert "python scripts/envtool.py" in message
    assert short_key not in message


@pytest.mark.parametrize(
    ("key", "error"),
    [
        (None, EnvironmentNotFoundError),
        ("", EnvironmentBlankError),
        ("   ", EnvironmentBlankError),
        ("none", EnvironmentBlankError),
    ],
    ids=["missing", "empty", "whitespace", "none"],
)
def test_absent_key_stops_startup(load_settings, key, error):
    with pytest.raises(error):
        load_settings(key)


@pytest.mark.parametrize(
    ("previous_keys", "expected"),
    [
        ("none", ()),
        ("", ()),
        ("a,,b", ("a", "b")),
        (" old-key-1 , old-key-2 ", ("old-key-1", "old-key-2")),
    ],
    ids=["none", "empty", "empty-item-dropped", "items-stripped"],
)
def test_previous_keys_are_read_into_a_tuple(load_settings, key_pair, previous_keys, expected):
    module = load_settings(VALID_KEY, previous_keys)

    assert expected == getattr(module, key_pair[1])
