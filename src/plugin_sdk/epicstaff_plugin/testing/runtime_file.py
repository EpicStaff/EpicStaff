"""Writing runtime files for tests, the way the EpicStaff node writes them."""

import os
import secrets
from pathlib import Path
from typing import Any

from epicstaff_plugin.contracts.runtime import RUNTIME_FILE_FORMAT, RuntimeFile
from epicstaff_plugin.testing.context_signer import ContextSigner

DEFAULT_API_URL = "http://epicstaff-api:8081/api/"
SERVICE_ACCOUNT_KEY_PREFIX = "esp-"


def service_account_key() -> str:
    """Return a new key in the form EpicStaff mints service-account keys in."""
    return SERVICE_ACCOUNT_KEY_PREFIX + secrets.token_urlsafe(32)


def write_runtime_file(
    path: str | os.PathLike[str], *, signer: ContextSigner | None = None, **overrides: Any
) -> RuntimeFile:
    """Write a valid runtime file to `path` and return it.

    The plugin, issuer and JWKS come from `signer` (a new one when none is given), so the
    contexts it issues, and the hook calls a `HookSigner` over it signs, verify against the
    file. `overrides` replace top-level fields (`settings={"units": "imperial"}`,
    `secret_settings=...`, `public_paths=...`, `service_accounts={"3": {"key":
    service_account_key(), "org_name": "Acme", "grant_state": "active"}}`). The file is
    replaced with a rename, as the node does, so a running `RuntimeConfig` sees the change.

    Raises:
        pydantic.ValidationError: The overrides do not make a valid runtime file.
    """
    signer = signer or ContextSigner()
    document: dict[str, Any] = {
        "format": RUNTIME_FILE_FORMAT,
        "plugin": {"identifier": signer.plugin_identifier, "version": signer.plugin_version},
        "issuer": signer.issuer,
        "public_url": f"https://{signer.plugin_identifier}.plugins.epicstaff.test",
        "epicstaff_public_url": signer.issuer,
        "epicstaff_api_url": DEFAULT_API_URL,
        "settings": {},
        "secret_settings": {},
        "service_accounts": {},
        "jwks": signer.jwks.model_dump(mode="json"),
        "public_paths": [],
        **overrides,
    }
    runtime_file = RuntimeFile.model_validate(document)
    destination = Path(path)
    temporary = destination.with_name(f".{destination.name}.{secrets.token_hex(4)}.tmp")
    try:
        temporary.write_text(runtime_file.model_dump_json(), encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return runtime_file
