from dataclasses import dataclass

from loguru import logger

from storage_credentials.exceptions import CredentialScopeValidationError
from storage_credentials.resource_names import TRASH_DIRECTORY


@dataclass(frozen=True)
class ScopedFolders:
    """Validated folders, namespaced under the org prefix.

    `own` are the run's own folders; `shared` are the allowed paths outside them.
    """

    shared: frozenset[str]
    own: frozenset[str]


class CredentialScopeValidator:
    """Validates a trusted scope (org_id, storage_org_prefix,
    storage_allowed_paths) before any MinIO API call is made -- cheaper and
    faster than letting MinIO itself reject a malformed request."""

    def validate(
        self,
        *,
        org_id: int,
        storage_org_prefix: str,
        storage_allowed_paths: list[str] | None,
        own_paths: list[str] | None = None,
    ) -> ScopedFolders:
        """Returns the concrete folders the temporary account should be scoped
        to (already namespaced under `storage_org_prefix`): the run's `own_paths`
        and the rest of `storage_allowed_paths` as shared folders."""
        if not org_id or not storage_org_prefix:
            raise CredentialScopeValidationError(
                "This request is missing required information to access file storage."
            )

        normalized_org_prefix = storage_org_prefix.strip().strip("/")
        if not normalized_org_prefix:
            raise CredentialScopeValidationError(
                "This request is missing required information to access file storage."
            )

        if not storage_allowed_paths:
            # Fail closed: an empty/missing storage_allowed_paths must not
            # default to org-wide access. Every caller that legitimately
            # wants storage must pass an explicit, narrow path.
            logger.warning(
                "storage_allowed_paths is empty for org_id={}: no session-scoped path was "
                "added (missing session_id) and no graph-level storage files are configured.",
                org_id,
            )
            raise CredentialScopeValidationError()

        own_folders = self._namespaced(normalized_org_prefix, own_paths or [])
        allowed_folders = self._namespaced(normalized_org_prefix, storage_allowed_paths)
        return ScopedFolders(shared=frozenset(allowed_folders - own_folders), own=own_folders)

    @staticmethod
    def _namespaced(normalized_org_prefix: str, paths: list[str]) -> frozenset[str]:
        scoped_folders: set[str] = set()
        for path in paths:
            normalized_path = path.strip().lstrip("/")
            if not normalized_path:
                raise CredentialScopeValidationError("One of the configured file paths is empty.")
            if ".." in normalized_path.split("/"):
                raise CredentialScopeValidationError(f"This file path isn't allowed: '{path}'.")
            if normalized_path.split("/", 1)[0] == TRASH_DIRECTORY:
                raise CredentialScopeValidationError(f"This file path isn't allowed: '{path}'.")
            scoped_folders.add(f"{normalized_org_prefix}/{normalized_path}")
        return frozenset(scoped_folders)


credential_scope_validator = CredentialScopeValidator()
