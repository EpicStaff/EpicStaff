from collections.abc import Callable

from django.core.exceptions import ValidationError

from tables.import_export.constants import IMPORT_VERSION


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
    def convert(cls, data: dict) -> dict:
        """
        Convert import data dict to the current IMPORT_VERSION via chain of conversions

        Preconditions
            - data is non-empty dict
            - Partial data bundle is allowed (missing key are allowed)
            - Convertions MUST guard against missing keys
            - data["version"] is an int <= IMPORT_VERSION (default to 1 if absent)
            - A migration func is registered for every version
        Postconditions
            - Returned dict has data["version"] == IMPORT_VERSION
            - All other keys are preserved/transformed by the convertion chain
        Raises
            - ValidationError:
                - if data["version"] > IMPORT_VERSION
                - if no convertion path exists for an intermediate version
        """
        version = data.get("version", 1)  # old files default to v1

        if version > IMPORT_VERSION:
            raise ValidationError(
                f"File version {version} is newer than supported {IMPORT_VERSION}"
            )

        while version < IMPORT_VERSION:
            if version not in cls._conversions:
                raise ValidationError(f"No migration path from version {version}")

            data = cls._conversions[version](data)
            version += 1
            data["version"] = version

        return data
