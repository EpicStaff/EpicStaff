"""`CredentialScopeValidator` is the last check before a trusted scope
(org_id/storage_org_prefix/storage_allowed_paths) is used to mint a MinIO
temporary service account (a sandboxed process claiming its own org_id/prefix).

Every entry of `storage_allowed_paths` is always namespaced under
`storage_org_prefix` (`f"{prefix}/{path}"`), so a path can only "escape" the
prefix through `..` traversal or an empty entry.
"""

import pytest
from loguru import logger

from storage_credentials.exceptions import CredentialScopeValidationError
from storage_credentials.services.scope_validator import CredentialScopeValidator


@pytest.fixture
def validator() -> CredentialScopeValidator:
    return CredentialScopeValidator()


@pytest.fixture
def warning_logs():
    """Collect loguru WARNING records emitted during the test."""
    records: list[str] = []
    sink_id = logger.add(records.append, level="WARNING")
    yield records
    logger.remove(sink_id)


@pytest.mark.parametrize(
    ("paths", "scoped_folders"),
    [
        (["flowA", "flowB/subdir"], {"org_1/flowA", "org_1/flowB/subdir"}),
        # Naming another org's prefix only creates a folder inside this org.
        (["org_2/secret"], {"org_1/org_2/secret"}),
    ],
    ids=["subfolders", "another-orgs-name-is-nested"],
)
def test_allowed_paths_are_scoped_under_the_org_prefix(validator, paths, scoped_folders):
    assert validator.validate(org_id=1, storage_org_prefix="org_1", storage_allowed_paths=paths) == scoped_folders


@pytest.mark.parametrize(
    ("org_id", "prefix", "paths"),
    [
        (1, "org_1", ["../org_2/secret"]),
        (1, "org_1", ["flowA/../../org_2/secret"]),
        # Fail closed: no paths must never default to the whole org prefix.
        (1, "org_1", None),
        (1, "org_1", []),
        (1, "org_1", [""]),
        (0, "org_1", ["flowA"]),
        (1, "", ["flowA"]),
    ],
    ids=["traversal", "nested-traversal", "paths-unset", "paths-empty", "empty-path", "no-org", "no-prefix"],
)
def test_a_scope_that_could_reach_outside_its_folders_is_rejected(validator, org_id, prefix, paths):
    with pytest.raises(CredentialScopeValidationError):
        validator.validate(org_id=org_id, storage_org_prefix=prefix, storage_allowed_paths=paths)


def test_a_missing_scope_is_explained_to_the_client_without_internals_but_logged_in_full(
    validator, warning_logs
):
    """The message is rendered verbatim to the API client; the diagnostic (which
    session, which org) belongs in the server log."""
    with pytest.raises(CredentialScopeValidationError) as exc_info:
        validator.validate(org_id=7, storage_org_prefix="org_7", storage_allowed_paths=[])

    message = str(exc_info.value)
    assert message == CredentialScopeValidationError.default_detail
    for internal_reference in ("converter_service", ".py", "session_id", "GraphStorageFile"):
        assert internal_reference not in message
    logged = "".join(warning_logs)
    assert "org_id=7" in logged
    assert "session_id" in logged


@pytest.mark.parametrize("path", [".recycle-bin", "/.recycle-bin/batch/report.pdf"])
def test_a_path_inside_the_recycle_bin_is_rejected(validator, path):
    with pytest.raises(CredentialScopeValidationError):
        validator.validate(org_id=1, storage_org_prefix="org_1", storage_allowed_paths=[path])
