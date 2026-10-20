from django.conf import settings
from epicstaff_plugin.package_layout import PackageArchive
from epicstaff_plugin.signing import (
    InvalidPackageSignatureError,
    SignatureVerdict,
    evaluate_package_signature,
    parse_trusted_keys,
)

from plugins.exceptions import InvalidSignatureError


def verify_package_signature(package: PackageArchive) -> SignatureVerdict:
    """Decide whether a package installs as Trusted, with the keys in PLUGINS_TRUSTED_SIGNING_KEYS.

    Raises:
        InvalidSignatureError: The package is signed, but the signature names another package
            or does not verify with the listed key it claims.
    """
    # The plugins.E004 start-up check has already refused malformed entries.
    trusted_keys = parse_trusted_keys(settings.PLUGINS_TRUSTED_SIGNING_KEYS)
    manifest = package.manifest
    try:
        return evaluate_package_signature(
            package.contents, manifest.id, manifest.version, package.signature, trusted_keys
        )
    except InvalidPackageSignatureError as error:
        raise InvalidSignatureError(detail=f"The package signature is invalid: {error}.") from None
