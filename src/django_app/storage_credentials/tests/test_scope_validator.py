"""`CredentialScopeValidator` is the last check before a trusted scope
(org_id/storage_org_prefix/storage_allowed_paths) is used to mint a MinIO
temporary service account (a sandboxed
process claiming its own org_id/prefix).

Real behaviour, confirmed by reading `scope_validator.py` rather than assumed
from the plan: every entry of `storage_allowed_paths` is always namespaced
under `storage_org_prefix` (`f"{prefix}/{path}"`), so a path can never
literally "escape" the prefix through this function the way an absolute,
already-prefixed path might in a naive implementation -- the only way to
trigger `CredentialScopeValidationError` on a path is `..` traversal or an
empty entry. See the discrepancy note on
`test_path_naming_another_orgs_prefix_is_nested_not_rejected` below.
"""

import pytest

from storage_credentials.exceptions import CredentialScopeValidationError
from storage_credentials.services.scope_validator import CredentialScopeValidator


@pytest.fixture
def validator() -> CredentialScopeValidator:
    return CredentialScopeValidator()


def test_paths_that_are_subsets_of_the_prefix_pass(validator):
    scoped_folders = validator.validate(
        org_id=1,
        storage_org_prefix="org_1",
        storage_allowed_paths=["flowA", "flowB/subdir"],
    )

    assert scoped_folders == {"org_1/flowA", "org_1/flowB/subdir"}


def test_path_traversal_is_rejected(validator):
    with pytest.raises(CredentialScopeValidationError):
        validator.validate(
            org_id=1,
            storage_org_prefix="org_1",
            storage_allowed_paths=["../org_2/secret"],
        )


def test_path_traversal_in_a_nested_segment_is_rejected(validator):
    with pytest.raises(CredentialScopeValidationError):
        validator.validate(
            org_id=1,
            storage_org_prefix="org_1",
            storage_allowed_paths=["flowA/../../org_2/secret"],
        )


def test_empty_storage_allowed_paths_defaults_to_the_whole_org_prefix(validator):
    """DISCREPANCY vs. the test plan: the plan asked to "fix the actual
    behaviour, whichever it is" for an empty `storage_allowed_paths` -- here
    it is a deliberate default (the whole org folder), not an error. The
    docstring in scope_validator.py explicitly calls this out as mirroring
    the pre-existing sandbox-side `_scoped_folders()` default."""
    scoped_folders = validator.validate(
        org_id=1, storage_org_prefix="org_1", storage_allowed_paths=None
    )

    assert scoped_folders == {"org_1/"}


def test_empty_list_storage_allowed_paths_also_defaults_to_the_whole_org_prefix(
    validator,
):
    scoped_folders = validator.validate(
        org_id=1, storage_org_prefix="org_1", storage_allowed_paths=[]
    )

    assert scoped_folders == {"org_1/"}


def test_missing_org_id_is_rejected(validator):
    with pytest.raises(CredentialScopeValidationError):
        validator.validate(
            org_id=0, storage_org_prefix="org_1", storage_allowed_paths=["flowA"]
        )


def test_missing_storage_org_prefix_is_rejected(validator):
    with pytest.raises(CredentialScopeValidationError):
        validator.validate(
            org_id=1, storage_org_prefix="", storage_allowed_paths=["flowA"]
        )


def test_an_empty_path_entry_is_rejected(validator):
    with pytest.raises(CredentialScopeValidationError):
        validator.validate(
            org_id=1, storage_org_prefix="org_1", storage_allowed_paths=[""]
        )


def test_path_naming_another_orgs_prefix_is_nested_not_rejected(validator):
    """DISCREPANCY vs. the test plan: the plan expected a path like
    "org_2/..." under `storage_org_prefix="org_1"` to raise
    `CredentialScopeValidationError` ("path outside the org prefix"). The
    real implementation always prepends `storage_org_prefix` to every entry
    (`f"{prefix}/{path}"`), so this string is not treated as an absolute,
    escaping path -- it is nested one level deeper under org_1, and MinIO's
    policy Resource ends up scoped to `org_1/org_2/...`, which is still
    fully inside org_1's own prefix and not a cross-org leak. There is no
    code path in this validator that lets a `storage_allowed_paths` entry
    resolve outside `storage_org_prefix` short of `..` traversal."""
    scoped_folders = validator.validate(
        org_id=1, storage_org_prefix="org_1", storage_allowed_paths=["org_2/secret"]
    )

    assert scoped_folders == {"org_1/org_2/secret"}
