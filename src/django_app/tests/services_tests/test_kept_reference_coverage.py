"""Every serializer field that links to a row which keeps its links while binned
(a secret, a webhook trigger, a voice channel) keeps that link on an unchanged save."""

import pytest
from rest_framework.relations import ManyRelatedField, PrimaryKeyRelatedField
from tables.serializers.utils.soft_delete_fields import KeptLinkPrimaryKeyRelatedField
from tables.services.soft_delete import keeps_references
from tests.services_tests.test_secret_reference_coverage import (
    _all_serializer_classes,
    _try_instantiate,
)

#: ("SerializerClassName", "field_name") -> why a live-only field is right there.
EXEMPT: dict[tuple[str, str], str] = {
    ("QuickstartSerializer", "api_key_secret_id"): (
        "Quickstart creates a new config, so its secret is always a new link."
    ),
    ("WebhookTriggerNodeImportSerializer", "webhook_trigger_id"): (
        "Import creates new nodes: a new link to a binned trigger stays refused."
    ),
    ("WebhookTriggerNodeImportSerializer", "webhook_trigger"): (
        "Import creates new nodes: a new link to a binned trigger stays refused."
    ),
    ("TelegramTriggerNodeImportSerializer", "webhook_trigger_id"): (
        "Import creates new nodes: a new link to a binned trigger stays refused."
    ),
    ("TelegramTriggerNodeImportSerializer", "webhook_trigger"): (
        "Import creates new nodes: a new link to a binned trigger stays refused."
    ),
    ("TwilioChannelSerializer", "channel"): (
        "The Twilio settings belong to their voice channel and go to the recycle bin with it, "
        "so they are never saved while that channel is binned."
    ),
    ("_TwilioChannelReadSerializer", "channel"): (
        "The Twilio settings belong to their voice channel and go to the recycle bin with it, "
        "so they are never saved while that channel is binned."
    ),
    ("_TwilioChannelInternalSerializer", "channel"): (
        "The Twilio settings belong to their voice channel and go to the recycle bin with it, "
        "so they are never saved while that channel is binned."
    ),
}


def _kept_reference_fields(serializer):
    """(name, relation) for writable related fields whose target keeps its links while binned."""
    for name, field in serializer.get_fields().items():
        relation = field.child_relation if isinstance(field, ManyRelatedField) else field
        if not isinstance(relation, PrimaryKeyRelatedField) or relation.read_only:
            continue
        queryset = getattr(relation, "queryset", None)
        if queryset is not None and keeps_references(queryset.model):
            yield name, relation


@pytest.mark.django_db
def test_every_kept_reference_field_keeps_binned_links():
    live_only = []
    for serializer_class in _all_serializer_classes():
        serializer, error = _try_instantiate(serializer_class)
        if serializer is None:
            continue
        try:
            fields = list(_kept_reference_fields(serializer))
        except Exception:
            # Abstract bases without a Meta.model; the secret coverage test tracks them.
            continue
        for name, relation in fields:
            key = (serializer_class.__name__, name)
            if not isinstance(relation, KeptLinkPrimaryKeyRelatedField) and key not in EXEMPT:
                live_only.append(f"{serializer_class.__module__}.{key[0]}.{name}")

    assert not live_only, (
        "These fields refuse an unchanged link to a binned row; use "
        "KeptLinkPrimaryKeyRelatedField or add them to EXEMPT with a reason:\n"
        + "\n".join(sorted(live_only))
    )
