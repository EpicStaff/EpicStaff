"""`epicstaff-plugin keygen`: create a signing key pair in minisign's format."""

import os
import re
from pathlib import Path

from epicstaff_plugin.cli.output import EXIT_OK, UsageError
from epicstaff_plugin.signing import generate_secret_key

SECRET_KEY_SUFFIX = ".key"
PUBLIC_KEY_SUFFIX = ".pub"
_NAME_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]+")


def keygen(prefix: Path) -> int:
    secret_path = prefix.with_name(prefix.name + SECRET_KEY_SUFFIX)
    public_path = prefix.with_name(prefix.name + PUBLIC_KEY_SUFFIX)
    for path in (secret_path, public_path):
        if path.exists():
            raise UsageError(f"{path} already exists; choose another --out prefix")
    secret_key = generate_secret_key()
    public_key = secret_key.public_key
    _write_new_file(secret_path, secret_key.to_file_text(), mode=0o600)
    _write_new_file(public_path, public_key.to_file_text(), mode=0o644)
    print(f"key id: {public_key.display_id}")
    print(f"secret key: {secret_path} (unencrypted; keep it private)")
    print(f"public key: {public_path}")
    print(f"PLUGINS_TRUSTED_SIGNING_KEYS entry: {_key_name(prefix)}:{public_key.to_text()}")
    return EXIT_OK


def _write_new_file(path: Path, text: str, *, mode: int) -> None:
    # O_EXCL: never overwrite a key, and create the secret key with its final mode, so it is
    # never readable by others, not even for a moment.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "w", encoding="ascii") as stream:
        stream.write(text)


def _key_name(prefix: Path) -> str:
    name = _NAME_CHARACTERS.sub("-", prefix.name).strip("-._")
    return name[:64] or "plugin-signing-key"
