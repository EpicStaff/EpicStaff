import json
from collections.abc import Callable

from tables.import_export.constants import IMPORT_VERSION
from tables.import_export.version_conversions.exceptions import UnsupportedImportVersionError


def file_version(data: dict) -> int:
    """Return an export file's version; a file from before the version field is version 1.

    Raises:
        UnsupportedImportVersionError: The version is not a whole number.
    """
    version = data.get("version", 1)
    # bool is a subclass of int: `"version": true` must not import as version 1.
    if not isinstance(version, int) or isinstance(version, bool):
        raise UnsupportedImportVersionError(
            f"File version must be a whole number, got {json.dumps(version)}"
        )
    return version


class VersionConverter:
    """
    Applies a chain of conversions to bring import data
    from any old version to IMPORT_VERSION
    """

    # Ordered registry: {from_version: migration_func}
    _conversions: dict[int, Callable[[dict], dict]] = {}

    @classmethod
    def register(cls, from_version: int):
        """
        Decorator to register a concrete version converter
        """

        def decorator(func):
            cls._conversions[from_version] = func
            return func

        return decorator

    @classmethod
    def supported_version(cls, data: dict) -> int:
        """Return the file's version when this release reads it.

        Raises:
            UnsupportedImportVersionError: The version is not a whole number, is
                below 1 (no release wrote one), or is newer than IMPORT_VERSION.
        """
        version = file_version(data)
        if version < 1:
            raise UnsupportedImportVersionError(
                f"File version {version} is older than the first export version 1"
            )
        if version > IMPORT_VERSION:
            raise UnsupportedImportVersionError(
                f"File version {version} is newer than supported {IMPORT_VERSION}"
            )
        return version

    @classmethod
    def convert(cls, data: dict) -> dict:
        """
        Convert import data dict to the current IMPORT_VERSION via chain of conversions

        Preconditions
            - data is non-empty dict
            - Partial data bundle is allowed (missing key are allowed)
            - Convertions MUST guard against missing keys
            - Entries and the nested values convertions read have the shape an
              export writes; an uploaded file is checked first by
              preparation.convert_to_current_version
            - data["version"] is an int <= IMPORT_VERSION (default to 1 if absent)
            - A migration func is registered for every version
        Postconditions
            - Returned dict has data["version"] == IMPORT_VERSION
            - All other keys are preserved/transformed by the convertion chain
        Raises
            - UnsupportedImportVersionError:
                - if data["version"] is not a whole number
                - if data["version"] < 1 or > IMPORT_VERSION
                - if no convertion path exists for an intermediate version
        """
        version = cls.supported_version(data)

        while version < IMPORT_VERSION:
            if version not in cls._conversions:
                raise UnsupportedImportVersionError(f"No migration path from version {version}")

            data = cls._conversions[version](data)
            version += 1
            data["version"] = version

        return data
