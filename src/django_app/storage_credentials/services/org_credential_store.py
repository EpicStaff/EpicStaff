from dataclasses import dataclass

from rbac.models import Organization
from tables.models import Secret
from tables.services.secrets.encryption import secret_encryption
from tables.services.secrets.secret_service import secret_service

from storage_credentials.constants import SECRET_NAME_ORG_STORAGE_USER
from storage_credentials.exceptions import OrgStorageCredentialMissingError

_CREDENTIAL_SEPARATOR = ":"


@dataclass(frozen=True)
class OrgStorageCredentials:
    access_key: str
    secret_key: str


class OrgCredentialStore:
    """The only place that reads or writes `Secret(system=True,
    name=SECRET_NAME_ORG_STORAGE_USER)` -- an organization's org-level storage IAM
    user credentials. Bypasses SecretViewSet/SecretSerializer entirely; those
    filter `system=True` rows out on purpose (never exposed via the
    user-facing Secret API)."""

    def save(self, *, org: Organization, access_key: str, secret_key: str) -> Secret:
        """(Re)provision this org's stored credential. A prior row is deleted first:
        `Secret` enforces one row per (org, name), and reactivation always mints a
        brand new storage user rather than resurrecting the deprovisioned one."""
        Secret.all_objects.filter(org=org, name=SECRET_NAME_ORG_STORAGE_USER, system=True).delete()
        text = f"{access_key}{_CREDENTIAL_SEPARATOR}{secret_key}"
        return secret_service.create(
            text=text,
            system=True,
            org=org,
            name=SECRET_NAME_ORG_STORAGE_USER,
        )

    def get(self, *, org_id: int) -> OrgStorageCredentials:
        secret = Secret.all_objects.filter(
            org_id=org_id, name=SECRET_NAME_ORG_STORAGE_USER, system=True
        ).first()
        if secret is None:
            raise OrgStorageCredentialMissingError(
                f"No active org-level storage credential for org_id={org_id}."
            )
        plaintext = secret_encryption.decrypt(encryptedtext=secret.value)
        access_key, _, secret_key = plaintext.partition(_CREDENTIAL_SEPARATOR)
        return OrgStorageCredentials(access_key=access_key, secret_key=secret_key)

    def exists(self, *, org_id: int) -> bool:
        secret = Secret.all_objects.filter(
            org_id=org_id, name=SECRET_NAME_ORG_STORAGE_USER, system=True
        ).first()
        return secret is not None

    def delete(self, *, org_id: int) -> None:
        """Delete this org's stored credential. If no credential exists for this
        org, this is a safe no-op (consistent with cascade delete on Organization
        deletion, which may have already removed the Secret)."""
        Secret.all_objects.filter(
            org_id=org_id, name=SECRET_NAME_ORG_STORAGE_USER, system=True
        ).delete()


org_credential_store = OrgCredentialStore()
