from dataclasses import dataclass

from tables.models import Organization, Secret
from tables.services.secrets.encryption import secret_encryption
from tables.services.secrets.secret_service import secret_service

from storage_credentials.constants import SECRET_NAME_ORG_MINIO_USER
from storage_credentials.exceptions import OrgStorageCredentialMissingError

_CREDENTIAL_SEPARATOR = ":"


@dataclass(frozen=True)
class OrgMinioCredentials:
    access_key: str
    secret_key: str


class OrgCredentialStore:
    """The only place that reads or writes `Secret(system=True,
    name=SECRET_NAME_ORG_MINIO_USER)` -- an organization's org-level MinIO IAM
    user credentials. Bypasses SecretViewSet/SecretSerializer entirely; those
    filter `system=True` rows out on purpose (never exposed via the
    user-facing Secret API)."""

    def save(self, *, org: Organization, access_key: str, secret_key: str) -> Secret:
        """(Re)provision this org's stored credential. A prior row (e.g. one
        marked revoked by `mark_revoked`) is deleted first: `Secret` enforces
        one row per (org, name), and reactivation always mints a brand new
        MinIO user rather than resurrecting the deprovisioned one."""
        Secret.objects.filter(
            org=org, name=SECRET_NAME_ORG_MINIO_USER, system=True
        ).delete()
        text = f"{access_key}{_CREDENTIAL_SEPARATOR}{secret_key}"
        return secret_service.create(
            text=text,
            system=True,
            org=org,
            name=SECRET_NAME_ORG_MINIO_USER,
        )

    def get(self, *, org_id: int) -> OrgMinioCredentials:
        secret = Secret.objects.filter(
            org_id=org_id, name=SECRET_NAME_ORG_MINIO_USER, system=True
        ).first()
        if secret is None or secret.metadata.get("revoked") is True:
            raise OrgStorageCredentialMissingError(
                f"No active org-level MinIO credential for org_id={org_id}."
            )
        plaintext = secret_encryption.decrypt(encryptedtext=secret.value)
        access_key, _, secret_key = plaintext.partition(_CREDENTIAL_SEPARATOR)
        return OrgMinioCredentials(access_key=access_key, secret_key=secret_key)

    def exists(self, *, org_id: int) -> bool:
        secret = Secret.objects.filter(
            org_id=org_id, name=SECRET_NAME_ORG_MINIO_USER, system=True
        ).first()
        return secret is not None and secret.metadata.get("revoked") is not True

    def mark_revoked(self, *, org_id: int) -> None:
        Secret.objects.filter(
            org_id=org_id, name=SECRET_NAME_ORG_MINIO_USER, system=True
        ).update(metadata={"revoked": True})


org_credential_store = OrgCredentialStore()
