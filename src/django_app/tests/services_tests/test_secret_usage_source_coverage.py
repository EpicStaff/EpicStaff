"""Coverage test for USAGE_SOURCES: every model field pointing at Secret must be registered or exempt."""

# USAGE_SOURCES (tables/services/secrets/usage_sources.py) answers "what uses this
# secret?" for the secrets list and detail endpoints. Unlike the sibling
# secret_reference_fields registry (see test_secret_reference_coverage.py), it had no
# coverage test of its own -- which is exactly how the four provider-specific realtime
# FKs (OpenAIRealtimeConfig.api_key_secret and .transcription_api_key_secret,
# ElevenLabsRealtimeConfig.api_key_secret, GeminiRealtimeConfig.api_key_secret) went
# unregistered: all four are on_delete=SET_NULL, so a secret used only through one of
# them silently reports zero usage instead of "hidden".
#
# This walks every concrete model in the tables app for forward FK/OneToOne/ManyToMany
# fields whose related_model is Secret, and checks each one is covered by a
# USAGE_SOURCES entry (mapped back to a (model, field) pair via secret_path) or listed
# in EXEMPT with a written reason.

import pytest
from django.apps import apps

from tables.models import PythonCode, Secret
from tables.services.secrets.usage_sources import USAGE_SOURCES, UsageSource

# Nothing here touches the database, but tests/conftest.py has a session-scoped
# autouse flush_test_db_once fixture whose flush would target the real `crew` dev
# database unless a test pulls in proper test-database setup -- same reasoning as
# test_api_docs_toggle.py and test_required_signing_keys.py.
pytestmark = pytest.mark.django_db

#: (model, field_name) pairs deliberately left off USAGE_SOURCES. Empty: every
#: Secret-referencing field discovered so far is registered. An entry here must carry
#: a one-line reason and must be called out in the task report -- an unexplained
#: exemption defeats the point of this test.
EXEMPT: set[tuple[type, str]] = set()

#: The number of (model, field) pairs the walk discovers today: the 9 single-FK
#: non-declaration sources, the one PythonCode.secrets M2M (which covers all six
#: PYTHON_CODE_SITES entries at once, since they all resolve through that same field),
#: and the four provider-specific realtime FKs this task registers. A floor, not an
#: exact match, so a legitimately new Secret-referencing field can push it up -- but it
#: must never silently drop, e.g. by a model losing its app_label or a field being
#: renamed out from under secret_path's string matching.
MINIMUM_DISCOVERED_SECRET_FIELD_COUNT = 14


def _discover_secret_fk_fields() -> set[tuple[type, str]]:
    """Every (model, field_name) in the tables app with a forward FK/O2O/M2M to Secret."""
    pairs = set()
    for model in apps.get_app_config(app_label="tables").get_models():
        for field in list(model._meta.fields) + list(model._meta.many_to_many):
            if getattr(field, "related_model", None) is Secret:
                pairs.add((model, field.name))
    return pairs


def _model_field_for(*, source: UsageSource) -> tuple[type, str]:
    """The (model, field_name) pair one USAGE_SOURCES entry actually covers."""
    # Declaration sites (PYTHON_CODE_SITES, e.g. "python_code__secrets__id" or
    # "pre_python_code__secrets__id") all resolve through PythonCode.secrets -- the
    # one M2M field the walk discovers -- not through the differently-named FK each
    # site uses to reach PythonCode. Six USAGE_SOURCES entries collapse onto this one
    # pair, which is expected: coverage is per discovered field, not per source.
    if source.secret_path.endswith("__secrets__id"):
        return PythonCode, "secrets"
    # Every other current entry is a plain FK/O2O whose secret_path is "<field>_id".
    if source.secret_path.endswith("_id") and "__" not in source.secret_path:
        return source.model, source.secret_path[: -len("_id")]
    raise AssertionError(
        f"USAGE_SOURCES entry for {source.model.__name__} has secret_path "
        f"{source.secret_path!r}, which this coverage test does not know how to map "
        "to a model field. Add explicit handling in _model_field_for rather than "
        "letting it silently miscount."
    )


def test_every_secret_referencing_field_is_registered_or_exempt():
    discovered = _discover_secret_fk_fields()
    covered = {_model_field_for(source=source) for source in USAGE_SOURCES}

    print(
        f"Secret-referencing fields discovered ({len(discovered)}): "
        f"{sorted((model.__name__, field) for model, field in discovered)}"
    )
    print(
        f"Secret-referencing fields covered by USAGE_SOURCES ({len(covered)}): "
        f"{sorted((model.__name__, field) for model, field in covered)}"
    )

    assert len(discovered) >= MINIMUM_DISCOVERED_SECRET_FIELD_COUNT, (
        f"Only {len(discovered)} Secret-referencing field(s) were discovered, below "
        f"the floor of {MINIMUM_DISCOVERED_SECRET_FIELD_COUNT}. A field the walk used "
        "to see has gone missing -- e.g. a model moved out of the tables app, or a "
        "field was renamed -- so this test can no longer prove what it claims to."
    )

    missing = discovered - covered - EXEMPT
    assert not missing, (
        "These model fields reference Secret but have no USAGE_SOURCES entry and are "
        "not in EXEMPT with a written reason. Every one of these is on_delete=SET_NULL "
        "or similarly silent, so deleting a secret used only through one of them would "
        "not be reported as readable or hidden usage. Register a UsageSource for each, "
        "or add it to EXEMPT with a one-line reason: "
        + ", ".join(sorted(f"{model.__name__}.{field}" for model, field in missing))
    )
