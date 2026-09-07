"""Guard: no import/export serializer may expose a Secret FK or a credential.

Subtask 3 excluded these; this test exists so a future serializer change cannot
silently put credentials back into export bundles.
"""

import re

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

# Dynamic counterpart to FORBIDDEN_FIELD_NAMES: fails on ANY credential-shaped
# field name, not only the ones enumerated above, so a future secret-bearing
# field cannot slip into an export bundle unnoticed.
_CREDENTIAL_NAME_RE = re.compile(
    r"key|secret|token|password|passwd|credential|auth", re.IGNORECASE
)

# Credential-shaped names verified safe to export. `max_tokens` is a generation
# limit (matches on "token"), not a credential. Secret FKs (api_key_secret, ...)
# are already dropped via each serializer's Meta.exclude, so they never appear.
# headers/extra_headers carry only `secret(<name>)` markers (names, not raw
# values) and do not match the pattern, so they need no entry here.
SAFE_CREDENTIAL_SHAPED_FIELDS = {"max_tokens"}


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
def test_config_import_serializers_expose_no_unwhitelisted_credential_field():
    """Dynamic guard (AC #4): any credential-shaped field name a config export
    serializer starts exposing fails here until it is dropped, converted to a
    Secret FK, or consciously added to SAFE_CREDENTIAL_SHAPED_FIELDS."""
    checked = 0
    for subclass in BaseConfigImportSerializer.__subclasses__():
        if getattr(subclass.Meta, "model", None) is None:
            continue
        checked += 1
        exposed = set(subclass().get_fields())
        suspicious = {
            name for name in exposed if _CREDENTIAL_NAME_RE.search(name)
        } - SAFE_CREDENTIAL_SHAPED_FIELDS
        assert not suspicious, f"{subclass.__name__} exposes {sorted(suspicious)}"
    assert checked, "no concrete BaseConfigImportSerializer subclass found"


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


@pytest.mark.django_db
def test_python_code_export_omits_the_secret_declaration():
    """Secret is not an import/export entity, so its PKs are meaningless in another
    org. The declaration must not travel at all — only the code, which carries the
    names as get_secret() literals because it is user code."""
    from tables.import_export.serializers.python_tools import (
        PythonCodeImportSerializer,
    )
    from tables.models import PythonCode

    python_code = PythonCode.objects.create(
        code='def main(**kwargs):\n    return get_secret("EXPORTED_KEY")\n',
        entrypoint="main",
    )

    exported = PythonCodeImportSerializer(python_code).data

    assert "secrets" not in exported
    assert "secret_ids" not in exported
    # The name still travels, unavoidably: it is a literal inside user code.
    assert "EXPORTED_KEY" in exported["code"]
