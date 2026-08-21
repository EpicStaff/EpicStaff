import pytest
from django.core.exceptions import ImproperlyConfigured

from tables.services.rbac.first_setup_mode import FirstSetupMode


def test_open_allows_http():
    assert FirstSetupMode.is_http_allowed(FirstSetupMode.OPEN) is True


def test_cli_only_blocks_http():
    assert FirstSetupMode.is_http_allowed(FirstSetupMode.CLI_ONLY) is False


def test_unknown_mode_blocks_http():
    """Fail closed: an unrecognized value must never open the endpoint."""
    assert FirstSetupMode.is_http_allowed("sometimes") is False


def test_validate_accepts_known_modes():
    assert FirstSetupMode.validate("open") == FirstSetupMode.OPEN
    assert FirstSetupMode.validate("cli_only") == FirstSetupMode.CLI_ONLY


def test_validate_rejects_unknown_mode_and_names_it():
    with pytest.raises(ImproperlyConfigured) as exc:
        FirstSetupMode.validate("sometimes")
    assert "sometimes" in str(exc.value)
