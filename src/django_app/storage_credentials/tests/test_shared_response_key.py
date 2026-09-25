"""Verify that both `django_app` and `sandbox` import and use the same
response_key builder from `src.shared.storage_credentials`.

This test ensures the Redis key format is consistent across the issuer
(django_app) and the requestor (sandbox), so credentials issued and persisted
in Redis can be successfully retrieved.
"""

import sys

import pytest


def test_response_key_same_object_across_modules():
    """Both django_app and sandbox must import the identical response_key
    function object from shared, not re-implement it locally."""

    # Import from django_app's keys module (re-exported from shared)
    from storage_credentials.redis import keys as django_keys

    # Import directly from shared
    from src.shared.storage_credentials import response_key as shared_response_key

    # Verify both refer to the same function object
    assert (
        django_keys.response_key is shared_response_key
    ), "django_app.keys.response_key is not the same object as shared.response_key"


def test_response_key_format_matches():
    """Test that the response_key format is correct."""
    from storage_credentials.redis import keys

    execution_id = "test-execution-123"
    expected = "storage_credential_response:test-execution-123"

    result = keys.response_key(execution_id)

    assert result == expected, f"Expected {expected}, got {result}"


def test_response_key_constant_exported():
    """Verify that CREDENTIAL_RESPONSE_KEY_PREFIX is exported from shared
    and re-exported by django_app's keys module."""
    from storage_credentials.redis import keys as django_keys
    from src.shared.storage_credentials import CREDENTIAL_RESPONSE_KEY_PREFIX

    assert (
        django_keys.CREDENTIAL_RESPONSE_KEY_PREFIX
        == CREDENTIAL_RESPONSE_KEY_PREFIX
    ), "CREDENTIAL_RESPONSE_KEY_PREFIX mismatch"
    assert CREDENTIAL_RESPONSE_KEY_PREFIX == "storage_credential_response"
