"""Reading key files given on the command line."""

from pathlib import Path

from epicstaff_plugin.cli.output import UsageError
from epicstaff_plugin.signing import SecretKey, SignatureFormatError


def read_secret_key(path: Path) -> SecretKey:
    """Read an unencrypted minisign secret key, turning every problem into a usage error."""
    try:
        text = path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError) as error:
        raise UsageError(f"cannot read the secret key {path}: {error}") from None
    try:
        return SecretKey.from_file_text(text)
    except SignatureFormatError as error:
        raise UsageError(f"{path}: {error}") from None
