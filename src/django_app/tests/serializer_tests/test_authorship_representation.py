"""Every API serializer renders `created_by` / `last_edited_by` as a user summary, never an id.

The next authored serializer fails here until it carries AuthorSummarySerializerMixin
(or LastEditFieldsSerializerMixin, which includes it).
"""

import importlib
import inspect
from pathlib import Path

import pytest
from django.conf import settings
from rest_framework import serializers

from rbac.authorship.last_edit import OMIT_AUTHORSHIP_CONTEXT_KEY
from rbac.authorship.serializers import LastEditFieldsSerializerMixin
from rbac.authorship.user_summary import UserSummarySerializer

SCANNED_APPS = ("tables", "agents", "rbac")
# Import/export serializers write ids on purpose; the rest never render API responses.
SKIPPED_PACKAGES = frozenset({"tests", "migrations", "management", "import_export", "admin"})


def _module_names() -> list[str]:
    root = Path(settings.BASE_DIR)
    names = []
    for app in SCANNED_APPS:
        for path in sorted((root / app).rglob("*.py")):
            parts = path.relative_to(root).with_suffix("").parts
            if SKIPPED_PACKAGES & set(parts):
                continue
            if parts[-1] == "__init__":
                parts = parts[:-1]
            names.append(".".join(parts))
    return names


def _concrete_serializer_classes() -> list[type[serializers.BaseSerializer]]:
    found = {}
    for module_name in _module_names():
        module = importlib.import_module(module_name)
        for _, member in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(member, serializers.BaseSerializer)
                and member.__module__ == module_name
                and not issubclass(member, serializers.ListSerializer)
            ):
                found[f"{member.__module__}.{member.__qualname__}"] = member
    return [found[name] for name in sorted(found)]


SERIALIZER_CLASSES = _concrete_serializer_classes()


def _fields(serializer_class, context: dict) -> dict:
    return serializer_class(context=context).fields


def _is_last_edited_by_summary(field) -> bool:
    if isinstance(field, UserSummarySerializer):
        return True
    return isinstance(field, serializers.SerializerMethodField) and isinstance(
        field.parent, LastEditFieldsSerializerMixin
    )


def test_scan_finds_the_known_authored_serializers():
    names = {serializer_class.__name__ for serializer_class in SERIALIZER_CLASSES}

    assert {
        "LLMConfigSerializer",
        "LLMModelSerializer",
        "SecretSerializer",
        "AgentNodeSerializer",
        "SurfaceReadSerializer",
        "StorageFileSerializer",
        "FileItemSerializer",
    } <= names


@pytest.mark.parametrize(
    "serializer_class", SERIALIZER_CLASSES, ids=lambda serializer_class: serializer_class.__name__
)
def test_authorship_fields_render_user_summaries(serializer_class):
    fields = _fields(serializer_class, {})

    if "created_by" in fields:
        assert isinstance(fields["created_by"], UserSummarySerializer)
        assert fields["created_by"].read_only
    if "last_edited_by" in fields:
        assert _is_last_edited_by_summary(fields["last_edited_by"])


AUTHOR_EXPOSING_CLASSES = [
    serializer_class
    for serializer_class in SERIALIZER_CLASSES
    if "created_by" in _fields(serializer_class, {})
]


def test_scan_finds_author_exposing_serializers():
    # Guards the parametrized test below against passing vacuously: one known
    # author-exposing serializer per family must be in the scanned set.
    names = {serializer_class.__name__ for serializer_class in AUTHOR_EXPOSING_CLASSES}

    assert {
        "LLMConfigSerializer",
        "SecretSerializer",
        "AgentNodeSerializer",
        "GraphNoteSerializer",
        "SurfaceReadSerializer",
        "RealtimeChannelSerializer",
        "McpToolSerializer",
    } <= names


@pytest.mark.parametrize(
    "serializer_class",
    AUTHOR_EXPOSING_CLASSES,
    ids=lambda serializer_class: serializer_class.__name__,
)
def test_change_detection_state_keeps_the_author_id(serializer_class):
    fields = _fields(serializer_class, {OMIT_AUTHORSHIP_CONTEXT_KEY: True})

    assert not isinstance(fields["created_by"], UserSummarySerializer)
    assert "last_edited_by" not in fields
