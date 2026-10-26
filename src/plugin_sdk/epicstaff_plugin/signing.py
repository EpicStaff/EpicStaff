"""Package signatures: minisign-compatible Ed25519 over `CONTENTS.json`.

The formats are minisign's, so the reference `minisign` tool can create keys and signatures
EpicStaff accepts, and verify signatures `epicstaff-plugin sign` makes:

- public key: base64 of `"Ed" | key id (8 bytes) | Ed25519 public key (32 bytes)`;
- secret key: base64 of minisign's 158-byte secret key structure; only unencrypted keys are
  read here (an encrypted one must be used with `minisign` itself);
- signature: four lines -- the untrusted comment, base64 of `"ED" | key id | Ed25519
  signature over BLAKE2b-512(message)`, the trusted comment, and base64 of the Ed25519
  "global" signature over `signature || trusted comment`.

The trusted comment of a package signature names the plugin, its version and the SHA-256
of `CONTENTS.json`, so a signature cannot be moved onto another package.

This module is the only implementation of signature checks; EpicStaff and the CLI both use
`evaluate_package_signature`.
"""

import base64
import binascii
import hashlib
import re
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

KEY_ALGORITHM = b"Ed"
PREHASHED_SIGNATURE_ALGORITHM = b"ED"
UNENCRYPTED_KEY_DERIVATION = b"\x00\x00"
SCRYPT_KEY_DERIVATION = b"Sc"
CHECKSUM_ALGORITHM = b"B2"
KEY_ID_BYTES = 8
PUBLIC_KEY_BYTES = 32
SEED_BYTES = 32
SIGNATURE_BYTES = 64
SECRET_KEY_STRUCTURE_BYTES = 158
# The scrypt salt and its two 8-byte limits; minisign leaves them zero in an unencrypted key.
_KEY_DERIVATION_PARAMETER_BYTES = 32 + 16
_CHECKSUM_BYTES = 32

UNTRUSTED_COMMENT_PREFIX = "untrusted comment: "
TRUSTED_COMMENT_PREFIX = "trusted comment: "
PACKAGE_SIGNATURE_COMMENT = "signature from epicstaff-plugin"
MAX_COMMENT_LENGTH = 1024

TRUSTED_KEY_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

Trust = Literal["trusted", "untrusted"]
SignatureStatus = Literal["valid", "absent", "unknown_key"]


class SignatureFormatError(ValueError):
    """A key or signature file is not in minisign's format."""


class EncryptedSecretKeyError(SignatureFormatError):
    """The secret key is password-protected, which only `minisign` itself can use."""


class InvalidPackageSignatureError(Exception):
    """The package carries a signature that does not belong to it or does not verify."""

    def __init__(self, message: str, key_id: str | None):
        self.key_id = key_id
        super().__init__(message)


def _decode_base64(text: str, what: str) -> bytes:
    try:
        return base64.b64decode(text.strip(), validate=True)
    except (binascii.Error, ValueError):
        raise SignatureFormatError(f"{what} is not valid base64") from None


def display_key_id(key_id: bytes) -> str:
    """Return a key id as minisign prints it: 16 upper-case hex digits of the little-endian number."""
    return key_id[::-1].hex().upper()


@dataclass(frozen=True)
class PublicKey:
    """A minisign public key."""

    key_id: bytes
    key: bytes

    @property
    def display_id(self) -> str:
        return display_key_id(self.key_id)

    def to_text(self) -> str:
        """Return the key in its one-line form (`RW...`)."""
        return base64.b64encode(KEY_ALGORITHM + self.key_id + self.key).decode("ascii")

    def to_file_text(self) -> str:
        """Return the content of a minisign `.pub` file."""
        return (
            f"{UNTRUSTED_COMMENT_PREFIX}minisign public key {self.display_id}\n{self.to_text()}\n"
        )

    @classmethod
    def from_text(cls, text: str) -> "PublicKey":
        """Read a public key from its one-line form or from a whole `.pub` file.

        Raises:
            SignatureFormatError: The text is not a minisign Ed25519 public key.
        """
        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        if len(lines) == 2 and lines[0].startswith(UNTRUSTED_COMMENT_PREFIX):
            lines = lines[1:]
        if len(lines) != 1:
            raise SignatureFormatError("a public key is one base64 line")
        raw = _decode_base64(lines[0], "the public key")
        if len(raw) != 2 + KEY_ID_BYTES + PUBLIC_KEY_BYTES or raw[:2] != KEY_ALGORITHM:
            raise SignatureFormatError("not a minisign Ed25519 public key")
        return cls(key_id=raw[2 : 2 + KEY_ID_BYTES], key=raw[2 + KEY_ID_BYTES :])

    def verifies(self, signature: bytes, message: bytes) -> bool:
        try:
            Ed25519PublicKey.from_public_bytes(self.key).verify(signature, message)
        except InvalidSignature:
            return False
        return True


@dataclass(frozen=True)
class SecretKey:
    """An unencrypted minisign secret key."""

    key_id: bytes
    seed: bytes

    @property
    def public_key(self) -> PublicKey:
        public_bytes = (
            Ed25519PrivateKey.from_private_bytes(self.seed)
            .public_key()
            .public_bytes(Encoding.Raw, PublicFormat.Raw)
        )
        return PublicKey(key_id=self.key_id, key=public_bytes)

    def sign(self, message: bytes) -> bytes:
        return Ed25519PrivateKey.from_private_bytes(self.seed).sign(message)

    def to_file_text(self) -> str:
        """Return the content of an unencrypted secret key file, laid out as `minisign -G -W` does."""
        structure = (
            KEY_ALGORITHM
            + UNENCRYPTED_KEY_DERIVATION
            + CHECKSUM_ALGORITHM
            + bytes(_KEY_DERIVATION_PARAMETER_BYTES)
            + self.key_id
            + self.seed
            + self.public_key.key
            + bytes(_CHECKSUM_BYTES)
        )
        encoded = base64.b64encode(structure).decode("ascii")
        return f"{UNTRUSTED_COMMENT_PREFIX}minisign secret key (unencrypted)\n{encoded}\n"

    @classmethod
    def from_file_text(cls, text: str) -> "SecretKey":
        """Read an unencrypted minisign secret key file.

        Raises:
            EncryptedSecretKeyError: The key is password-protected.
            SignatureFormatError: The text is not a minisign Ed25519 secret key, or its
                checksum does not match.
        """
        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        if len(lines) != 2 or not lines[0].startswith(UNTRUSTED_COMMENT_PREFIX):
            raise SignatureFormatError("a secret key file has a comment line and a base64 line")
        raw = _decode_base64(lines[1], "the secret key")
        if len(raw) != SECRET_KEY_STRUCTURE_BYTES or raw[:2] != KEY_ALGORITHM:
            raise SignatureFormatError("not a minisign Ed25519 secret key")
        key_derivation = raw[2:4]
        if key_derivation == SCRYPT_KEY_DERIVATION:
            raise EncryptedSecretKeyError(
                "the secret key is password-protected; sign with the minisign tool instead"
            )
        if key_derivation != UNENCRYPTED_KEY_DERIVATION or raw[4:6] != CHECKSUM_ALGORITHM:
            raise SignatureFormatError("unsupported secret key parameters")
        offset = 6 + _KEY_DERIVATION_PARAMETER_BYTES
        key_id = raw[offset : offset + KEY_ID_BYTES]
        secret = raw[offset + KEY_ID_BYTES : offset + KEY_ID_BYTES + SEED_BYTES + PUBLIC_KEY_BYTES]
        checksum = raw[offset + KEY_ID_BYTES + SEED_BYTES + PUBLIC_KEY_BYTES :]
        # minisign 0.12 leaves the checksum of an unencrypted key zero; older versions filled it.
        if checksum not in (bytes(_CHECKSUM_BYTES), _secret_key_checksum(key_id, secret)):
            raise SignatureFormatError("the secret key checksum does not match")
        key = cls(key_id=key_id, seed=secret[:SEED_BYTES])
        if key.public_key.key != secret[SEED_BYTES:]:
            raise SignatureFormatError("the secret key does not match its public half")
        return key


def _secret_key_checksum(key_id: bytes, secret: bytes) -> bytes:
    return hashlib.blake2b(KEY_ALGORITHM + key_id + secret, digest_size=_CHECKSUM_BYTES).digest()


def generate_secret_key() -> SecretKey:
    """Create a new key pair with a random key id."""
    return SecretKey(key_id=secrets.token_bytes(KEY_ID_BYTES), seed=secrets.token_bytes(SEED_BYTES))


@dataclass(frozen=True)
class SignatureFile:
    """A parsed minisign signature file."""

    key_id: bytes
    signature: bytes
    trusted_comment: str
    global_signature: bytes

    @property
    def display_key_id(self) -> str:
        return display_key_id(self.key_id)

    @classmethod
    def from_text(cls, text: str) -> "SignatureFile":
        """Parse a minisign signature over a pre-hashed message.

        Raises:
            SignatureFormatError: The text is not such a signature (legacy, non-prehashed
                signatures are refused too).
        """
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        lines = [line.removesuffix("\r") for line in lines]
        if len(lines) != 4:
            raise SignatureFormatError("a signature file has exactly four lines")
        untrusted, encoded_signature, trusted, encoded_global = lines
        if not untrusted.startswith(UNTRUSTED_COMMENT_PREFIX):
            raise SignatureFormatError("the first line must be the untrusted comment")
        if not trusted.startswith(TRUSTED_COMMENT_PREFIX):
            raise SignatureFormatError("the third line must be the trusted comment")
        trusted_comment = trusted[len(TRUSTED_COMMENT_PREFIX) :]
        if len(trusted_comment) > MAX_COMMENT_LENGTH:
            raise SignatureFormatError("the trusted comment is too long")
        raw = _decode_base64(encoded_signature, "the signature")
        if len(raw) != 2 + KEY_ID_BYTES + SIGNATURE_BYTES:
            raise SignatureFormatError("the signature line has the wrong length")
        if raw[:2] != PREHASHED_SIGNATURE_ALGORITHM:
            raise SignatureFormatError(
                "only pre-hashed (ED) signatures are accepted; sign with minisign 0.10 or later"
            )
        global_signature = _decode_base64(encoded_global, "the trusted comment signature")
        if len(global_signature) != SIGNATURE_BYTES:
            raise SignatureFormatError("the trusted comment signature has the wrong length")
        return cls(
            key_id=raw[2 : 2 + KEY_ID_BYTES],
            signature=raw[2 + KEY_ID_BYTES :],
            trusted_comment=trusted_comment,
            global_signature=global_signature,
        )

    def verifies_with(self, public_key: PublicKey, message: bytes) -> bool:
        """Return whether both the signature and the trusted comment verify with `public_key`."""
        if public_key.key_id != self.key_id:
            return False
        prehash = hashlib.blake2b(message, digest_size=64).digest()
        signed_comment = self.signature + self.trusted_comment.encode("utf-8")
        return public_key.verifies(self.signature, prehash) and public_key.verifies(
            self.global_signature, signed_comment
        )


def sign(
    message: bytes, secret_key: SecretKey, *, trusted_comment: str, untrusted_comment: str
) -> str:
    """Return a minisign signature file over `message` (pre-hashed, as minisign does by default)."""
    if "\n" in trusted_comment or "\n" in untrusted_comment:
        raise ValueError("comments are single lines")
    prehash = hashlib.blake2b(message, digest_size=64).digest()
    signature = secret_key.sign(prehash)
    global_signature = secret_key.sign(signature + trusted_comment.encode("utf-8"))
    encoded_signature = base64.b64encode(
        PREHASHED_SIGNATURE_ALGORITHM + secret_key.key_id + signature
    ).decode("ascii")
    encoded_global = base64.b64encode(global_signature).decode("ascii")
    return (
        f"{UNTRUSTED_COMMENT_PREFIX}{untrusted_comment}\n{encoded_signature}\n"
        f"{TRUSTED_COMMENT_PREFIX}{trusted_comment}\n{encoded_global}\n"
    )


def package_trusted_comment(plugin_id: str, version: str, contents: bytes) -> str:
    """Return the trusted comment a package signature must carry."""
    digest = hashlib.sha256(contents).hexdigest()
    return f"plugin={plugin_id} version={version} contents_sha256={digest}"


def sign_package(contents: bytes, plugin_id: str, version: str, secret_key: SecretKey) -> str:
    """Return the `CONTENTS.json.minisig` text for a package."""
    return sign(
        contents,
        secret_key,
        trusted_comment=package_trusted_comment(plugin_id, version, contents),
        untrusted_comment=PACKAGE_SIGNATURE_COMMENT,
    )


@dataclass(frozen=True)
class TrustedKey:
    """A public key the operator trusts, with the name it is shown under."""

    name: str
    public_key: PublicKey


def parse_trusted_key(entry: str) -> TrustedKey:
    """Parse one `<name>:<RW... public key>` entry.

    Raises:
        SignatureFormatError: The entry is not in that form.
    """
    name, separator, key_text = entry.strip().partition(":")
    if not separator:
        raise SignatureFormatError("must be <name>:<minisign public key>")
    if not TRUSTED_KEY_NAME_PATTERN.match(name):
        raise SignatureFormatError(
            "the name must be 1-64 letters, digits, '.', '_' or '-', starting with a letter or digit"
        )
    return TrustedKey(name=name, public_key=PublicKey.from_text(key_text))


def parse_trusted_keys(entries: Iterable[str]) -> list[TrustedKey]:
    """Parse a list of trusted key entries, refusing repeated names or keys.

    Raises:
        SignatureFormatError: An entry is malformed, or a name or key id appears twice; the
            message names the entry.
    """
    keys: list[TrustedKey] = []
    for position, entry in enumerate(entries, start=1):
        try:
            key = parse_trusted_key(entry)
        except SignatureFormatError as error:
            raise SignatureFormatError(f"entry {position}: {error}") from None
        if any(existing.name == key.name for existing in keys):
            raise SignatureFormatError(f"entry {position}: the name {key.name!r} is used twice")
        if any(existing.public_key.key_id == key.public_key.key_id for existing in keys):
            raise SignatureFormatError(
                f"entry {position}: key {key.public_key.display_id} is listed twice"
            )
        keys.append(key)
    return keys


@dataclass(frozen=True)
class SignatureVerdict:
    """What a package's signature says about it."""

    trust: Trust
    signature: SignatureStatus
    key_id: str | None
    key_name: str | None


def evaluate_package_signature(
    contents: bytes,
    plugin_id: str,
    version: str,
    signature_text: str | None,
    trusted_keys: Iterable[TrustedKey],
) -> SignatureVerdict:
    """Decide whether a package is Trusted from its `CONTENTS.json` and signature.

    No signature, or one by a key the operator does not list, makes the package Untrusted.
    A signature by a listed key that verifies makes it Trusted.

    Raises:
        SignatureFormatError: The signature file is malformed.
        InvalidPackageSignatureError: The trusted comment does not name this package (checked for
            unknown keys too), or a listed key's signature does not verify.
    """
    if signature_text is None:
        return SignatureVerdict(trust="untrusted", signature="absent", key_id=None, key_name=None)
    signature = SignatureFile.from_text(signature_text)
    key_id = signature.display_key_id
    if signature.trusted_comment != package_trusted_comment(plugin_id, version, contents):
        raise InvalidPackageSignatureError(
            "the signature's trusted comment does not name this plugin, version and CONTENTS.json",
            key_id,
        )
    trusted_key = next(
        (key for key in trusted_keys if key.public_key.key_id == signature.key_id), None
    )
    if trusted_key is None:
        return SignatureVerdict(
            trust="untrusted", signature="unknown_key", key_id=key_id, key_name=None
        )
    if not signature.verifies_with(trusted_key.public_key, contents):
        raise InvalidPackageSignatureError(
            f"the signature does not verify with the trusted key {trusted_key.name!r}", key_id
        )
    return SignatureVerdict(
        trust="trusted", signature="valid", key_id=key_id, key_name=trusted_key.name
    )
