from storage_credentials.exceptions import CredentialScopeValidationError


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
    ) -> set[str]:
        """Returns the concrete set of folders the temporary account should
        be scoped to (already namespaced under `storage_org_prefix`)."""
        if not org_id or not storage_org_prefix:
            raise CredentialScopeValidationError(
                "Scope is missing org_id or storage_org_prefix."
            )

        normalized_org_prefix = storage_org_prefix.strip().strip("/")
        if not normalized_org_prefix:
            raise CredentialScopeValidationError("storage_org_prefix is empty.")

        if not storage_allowed_paths:
            # No explicit restriction narrower than the org's own prefix:
            # the whole org folder, same default as the pre-existing
            # sandbox-side _scoped_folders() this replaces.
            return {f"{normalized_org_prefix}/"}

        scoped_folders: set[str] = set()
        for path in storage_allowed_paths:
            normalized_path = path.strip().lstrip("/")
            if not normalized_path:
                raise CredentialScopeValidationError(
                    "storage_allowed_paths contains an empty path."
                )
            if ".." in normalized_path.split("/"):
                raise CredentialScopeValidationError(
                    f"Path traversal in storage_allowed_paths: '{path}'"
                )
            scoped_folders.add(f"{normalized_org_prefix}/{normalized_path}")

        return scoped_folders


credential_scope_validator = CredentialScopeValidator()
