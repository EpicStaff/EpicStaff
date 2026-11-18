"""The transport keys the service reads at import time.

SECRETS_TRANSPORT_KEY must not be blank; its length is Django's rule, not this
service's. SECRETS_TRANSPORT_PREVIOUS_KEYS is split on commas, each key stripped, and
`none`, an empty value and empty items yield no key. Each case reloads the settings
module under a patched environment.
"""

import importlib

import app.core.settings as settings_module
import pytest
from src.shared.envtools import EnvironmentBlankError


@pytest.fixture
def reload_settings_with_env():
    """Reload the settings module under patched variables, then restore both.

    A reload that raises leaves the module half re-executed, so it is always reloaded
    again under the original environment afterwards.
    """
    environment = pytest.MonkeyPatch()

    def reload(**variables: str):
        for name, value in variables.items():
            environment.setenv(name, value)
        return importlib.reload(settings_module).settings

    yield reload

    environment.undo()
    importlib.reload(settings_module)


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("none", []),
        ("", []),
        ("old-key-0001", ["old-key-0001"]),
        (" old-key-0001 , ,old-key-0002 ,", ["old-key-0001", "old-key-0002"]),
    ],
    ids=["none", "empty", "one", "padded-with-empty-items"],
)
def test_previous_transport_keys_are_split_stripped_and_empty_items_dropped(
    reload_settings_with_env, configured, expected
):
    previous_keys = reload_settings_with_env(
        SECRETS_TRANSPORT_PREVIOUS_KEYS=configured
    ).SECRETS_TRANSPORT_PREVIOUS_KEYS

    assert previous_keys == expected


@pytest.mark.parametrize("configured", ["", "   ", "none"])
def test_a_blank_transport_key_refuses_startup(reload_settings_with_env, configured):
    with pytest.raises(EnvironmentBlankError, match="SECRETS_TRANSPORT_KEY"):
        reload_settings_with_env(SECRETS_TRANSPORT_KEY=configured)


def test_a_short_transport_key_is_accepted(reload_settings_with_env):
    reloaded = reload_settings_with_env(SECRETS_TRANSPORT_KEY="short")

    assert reloaded.SECRETS_TRANSPORT_KEY == "short"
