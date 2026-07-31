"""Guard: no import/export serializer may expose a Secret FK or a credential.

Subtask 3 excluded these; this test exists so a future serializer change cannot
silently put credentials back into export bundles.
"""

import pytest

from tables.import_export.serializers.configs import BaseConfigImportSerializer
from tables.import_export.serializers.graph import (
    TelegramTriggerNodeImportSerializer as NestedTelegramImportSerializer,
)
from tables.import_export.serializers.mcp_tools import McpToolImportSerializer
from tables.import_export.serializers.telegram_trigger_node import (
    TelegramTriggerNodeImportSerializer,
)

FORBIDDEN_FIELD_NAMES = {
    "api_key",
    "api_key_secret",
    "auth",
    "auth_secret",
    "telegram_bot_api_key",
    "telegram_bot_api_key_secret",
}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "serializer_cls",
    [
        McpToolImportSerializer,
        TelegramTriggerNodeImportSerializer,
        NestedTelegramImportSerializer,
    ],
    ids=lambda cls: cls.__module__.rsplit(".", 1)[-1] + "." + cls.__name__,
)
def test_import_serializer_exposes_no_credential_field(serializer_cls):
    exposed = set(serializer_cls().get_fields())
    leaked = exposed & FORBIDDEN_FIELD_NAMES
    assert not leaked, f"{serializer_cls.__name__} exposes {sorted(leaked)}"


@pytest.mark.django_db
def test_base_config_import_serializer_exposes_no_credential_field():
    """BaseConfigImportSerializer has Meta.model = None, so it is exercised
    through a concrete subclass the way the export service uses it."""
    for subclass in BaseConfigImportSerializer.__subclasses__():
        if getattr(subclass.Meta, "model", None) is None:
            continue
        exposed = set(subclass().get_fields())
        leaked = exposed & FORBIDDEN_FIELD_NAMES
        assert not leaked, f"{subclass.__name__} exposes {sorted(leaked)}"


@pytest.mark.django_db
def test_at_least_one_config_subclass_was_actually_checked():
    """Without this, the loop above passes vacuously if the subclass registry
    is ever restructured."""
    concrete = [
        subclass
        for subclass in BaseConfigImportSerializer.__subclasses__()
        if getattr(subclass.Meta, "model", None) is not None
    ]
    assert concrete, "no concrete BaseConfigImportSerializer subclass found"
