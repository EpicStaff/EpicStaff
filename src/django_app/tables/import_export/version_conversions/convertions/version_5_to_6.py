from tables.import_export.version_conversions.base import VersionConverter


@VersionConverter.register(from_version=5)
def v5_to_v6(data: dict) -> dict:
    """
    v5 -> v6:
    - An export can be a zip archive: `export.json` plus the files it names. A v5
      file never carries a knowledge collection, so its entries need no change.
    """
    return data
